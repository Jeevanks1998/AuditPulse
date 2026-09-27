"""
api/auth.py

Authentication routes. The User model itself now lives in models/user.py
(re-exported below so existing `from api.auth import User` imports across
the codebase keep working); this module owns password/token handling and
the login/logout/me endpoints, and logs a History event for each
successful login.

There is intentionally no /auth/register (or /auth/login-email) here —
accounts are provisioned exclusively by an administrator through the
Access Portal sync (api/access_management.py). See the note above the
route definitions below before adding anything back.

Also exposes `get_current_user`, the dependency every other router in
api/ uses to identify the caller.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from config.settings import settings
from models.history import HistoryEventType, log_event
from models.user import User
from schemas.user import TokenOut, UserLogin, UserOut

router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# auto_error=False so an unauthenticated request reaches get_current_user and
# gets a clean 401 with a WWW-Authenticate header, rather than FastAPI's
# generic "Not authenticated" from the security dependency itself.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login", auto_error=False
)


# --------------------------------------------------------------------------
# Password / token helpers
# --------------------------------------------------------------------------
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def generate_api_key() -> str:
    """ap_live_<20 hex chars> — matches the shape seeded in the frontend mock db."""
    return "ap_live_" + secrets.token_hex(10)


def create_access_token(subject: str, expires_minutes: Optional[int] = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        subject: Optional[str] = payload.get("sub")
        if subject is None:
            raise JWTError("Missing subject")
        return subject
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# --------------------------------------------------------------------------
# Dependency: current user — imported by every other router in api/
# --------------------------------------------------------------------------
async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = decode_access_token(token)
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active or not user.auditpulse_access:
        # Mid-session revocation: the Access Portal can flip either flag
        # off after a token was already issued (see api/access_management.py).
        # A generic message here is deliberate — this dependency backs
        # every other route's auth, not just /auth/login, so it isn't the
        # place to distinguish "inactive" from "no AuditPulse access" the
        # way the login route below does; the person just gets signed out
        # either way and has to go through login to see which one it was.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive"
        )
    return user


# --------------------------------------------------------------------------
# Routes
#
# Deliberately just three: login, logout, me. There is no self-service
# /auth/register (and no /auth/login-email — see git history) — every
# AuditPulse account must already exist, created and activated by an
# administrator via the Access Portal sync (api/access_management.py).
# None of the routes below may create a User row; if you're tempted to
# add "if user doesn't exist: create it" anywhere in this file, don't —
# account creation only ever happens in api/access_management.py.
# --------------------------------------------------------------------------


@router.post("/login", response_model=TokenOut)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    """Internal login. Checked in order, no step skipped and no account
    ever created here — every AuditPulse account must already exist,
    created and activated by an administrator (see
    api/access_management.py, the Access Portal sync endpoint):

      1. Does the account exist?           -> "Invalid credentials"
      2. Is the account active?            -> "Your account is inactive"
      3. Does it have AuditPulse access?   -> "You don't have AuditPulse access"
      4. Is the password correct?          -> "Invalid credentials"

    Steps 1 and 4 deliberately share the same generic message so a
    failed request can't be used to confirm whether an email is
    registered.

    Phase 5: is_active and auditpulse_access are now two separate columns
    (see models/user.py), so — matching the Access Portal's own example —
    a user can be Active with AuditPulse Access: No and login is rejected
    with the AuditPulse-specific message, distinct from an inactive
    account. Checked in this order (active before auditpulse_access)
    since an inactive account is the more fundamental problem.
    """
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is inactive. Contact an org admin in the Access Portal.",
        )

    if not user.auditpulse_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have AuditPulse access.",
        )

    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    await log_event(db, user.id, HistoryEventType.LOGIN, description="Signed in")
    await db.commit()

    token = create_access_token(subject=str(user.id))
    return TokenOut(token=token, user=UserOut.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(current_user: User = Depends(get_current_user)):
    # Stateless JWTs: nothing to invalidate server-side. If you need
    # server-side revocation later, blocklist the token's jti in Redis here.
    return None


@router.get("/me", response_model=UserOut)
async def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user
