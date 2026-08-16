"""
api/auth.py

Authentication routes. The User model itself now lives in models/user.py
(re-exported below so existing `from api.auth import User` imports across
the codebase keep working); this module owns password/token handling and
the register/login/logout/me endpoints, and logs a History event for
each successful register/login.

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
from config.logging import logger
from config.settings import settings
from models.history import HistoryEventType, log_event
from models.user import User
from schemas.user import TokenOut, UserEmailLogin, UserLogin, UserOut, UserRegister

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

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive"
        )
    return user


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(
        name=payload.name,
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        company=payload.company or "",
        api_key=generate_api_key(),
    )
    db.add(user)
    await db.flush()

    await log_event(db, user.id, HistoryEventType.REGISTER, description=f"Account created ({user.email})")
    await db.commit()
    await db.refresh(user)

    logger.info(f"New account registered: {user.email}")
    token = create_access_token(subject=str(user.id))
    return TokenOut(token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.hashed_password):
        # Deliberately generic — mirrors the frontend's "Incorrect email or
        # password." message and avoids confirming which part was wrong.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    await log_event(db, user.id, HistoryEventType.LOGIN, description="Signed in")
    await db.commit()

    token = create_access_token(subject=str(user.id))
    return TokenOut(token=token, user=UserOut.model_validate(user))


@router.post("/login-email", response_model=TokenOut)
async def login_email(payload: UserEmailLogin, db: AsyncSession = Depends(get_db)):
    """Internal, passwordless sign-in: identify the caller by email alone.

    Finds the existing account for this email, or silently creates one
    (no password set by the user — a random one is stored server-side
    purely to satisfy the column) the first time this email signs in.
    Intended for internal/trusted use only, not a public-facing flow.
    """
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            name=payload.name or payload.email.split("@")[0],
            email=payload.email,
            hashed_password=get_password_hash(secrets.token_urlsafe(24)),
            api_key=generate_api_key(),
        )
        db.add(user)
        await db.flush()
        await log_event(db, user.id, HistoryEventType.REGISTER, description=f"Account created ({user.email})")
    elif not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="This account is inactive."
        )

    await log_event(db, user.id, HistoryEventType.LOGIN, description="Signed in (internal, email only)")
    await db.commit()
    await db.refresh(user)

    logger.info(f"Internal email-only login: {user.email}")
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
