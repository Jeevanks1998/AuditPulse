"""
Sign-in: email, then a Google Authenticator code. No passwords.

  POST /auth/login  {email}  -> step "setup" (show QR code) or "verify" (ask
                               for code), plus a short-lived challenge token
  POST /auth/verify {challenge_token, code} -> the session token

Any TOTP app works. Accounts are only created by the Access Portal sync
(api/access_management.py); there is no sign-up here.
Also provides get_current_user, used by every other router.
"""

import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

import pyotp
import segno
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from config.settings import settings
from models.history import HistoryEventType, log_event
from models.user import User
from schemas.user import LoginStepOut, TokenOut, TotpVerifyIn, UserLogin, UserOut

router = APIRouter()

# Name shown above the code in the authenticator app.
TOTP_ISSUER = "AuditPulse"

# How long a login challenge lasts. Setup is longer (time to install the app).
CHALLENGE_TTL_MINUTES = {"mfa_setup": 15, "mfa_login": 5}

# After MAX_CODE_FAILURES wrong codes, block code entry for CODE_LOCKOUT_SECONDS.
MAX_CODE_FAILURES = 5
CODE_LOCKOUT_SECONDS = 5 * 60
_code_failures: Dict[int, Tuple[int, float]] = {}

# auto_error=False so get_current_user returns a clean 401.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login", auto_error=False
)


# Tokens
def generate_api_key() -> str:
    """ap_live_<20 hex chars>"""
    return "ap_live_" + secrets.token_hex(10)


def _encode(subject: str, typ: str, expires_minutes: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload = {"sub": subject, "typ": typ, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(subject: str, expires_minutes: Optional[int] = None) -> str:
    """A session token, only issued after a correct code."""
    return _encode(subject, "access", expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)


def create_challenge_token(subject: str, typ: str) -> str:
    """Links /auth/login to /auth/verify; not accepted anywhere else."""
    return _encode(subject, typ, CHALLENGE_TTL_MINUTES[typ])


def _decode(token: str, allowed_types: Tuple[str, ...], error_detail: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    if payload.get("sub") is None or payload.get("typ") not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


def decode_access_token(token: str) -> str:
    # Only "access" tokens are sessions; challenge tokens and old password-login tokens are refused.
    return _decode(token, ("access",), "Could not validate credentials")["sub"]


# Authenticator (TOTP)
def _qr_data_uri(otpauth_uri: str) -> str:
    return segno.make(otpauth_uri, error="m").svg_data_uri(scale=5, border=2)


def _check_lockout(user_id: int) -> None:
    failures, locked_until = _code_failures.get(user_id, (0, 0.0))
    if locked_until and time.time() < locked_until:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many incorrect codes. Please wait a few minutes and try again.",
        )
    if locked_until and time.time() >= locked_until:
        _code_failures.pop(user_id, None)


def _record_failure(user_id: int) -> None:
    failures, _ = _code_failures.get(user_id, (0, 0.0))
    failures += 1
    locked_until = time.time() + CODE_LOCKOUT_SECONDS if failures >= MAX_CODE_FAILURES else 0.0
    _code_failures[user_id] = (failures, locked_until)


def _check_account(user: Optional[User]) -> User:
    """Account checks used by both login steps."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No AuditPulse account was found for that email.",
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
    return user

# Current user dependency
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
        # The portal can disable an account after sign-in; the session ends either way.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive"
        )
    if not user.mfa_enabled or user.auth_setup_required:
        # Authenticator was reset after sign-in: end the session so they set it up again.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your authenticator was reset. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# Routes: login, verify, logout, me.
# Never create users here; accounts only come from api/access_management.py.


@router.post("/login", response_model=LoginStepOut)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    """Step 1, email only. Checks: account exists, is active, has AuditPulse access.
    Then: no authenticator yet -> "setup" (QR code); otherwise -> "verify".
    """
    email = payload.email.strip().lower()
    result = await db.execute(select(User).where(func.lower(User.email) == email))
    user = _check_account(result.scalars().first())

    needs_setup = user.auth_setup_required or not user.mfa_enabled or not user.mfa_secret
    if not needs_setup:
        return LoginStepOut(
            step="verify",
            challenge_token=create_challenge_token(str(user.id), "mfa_login"),
            email=user.email,
        )

    # First setup (or after a reset): new secret. mfa_enabled stays False until a correct code.
    secret = pyotp.random_base32()
    user.mfa_secret = secret
    user.mfa_enabled = False
    user.auth_setup_required = True
    await db.commit()

    otpauth_uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=TOTP_ISSUER)
    return LoginStepOut(
        step="setup",
        challenge_token=create_challenge_token(str(user.id), "mfa_setup"),
        email=user.email,
        qr_code=_qr_data_uri(otpauth_uri),
        secret=secret,
        otpauth_uri=otpauth_uri,
    )


@router.post("/verify", response_model=TokenOut)
async def verify(payload: TotpVerifyIn, db: AsyncSession = Depends(get_db)):
    """Step 2: the 6-digit code. Returns the session."""
    claims = _decode(
        payload.challenge_token,
        ("mfa_setup", "mfa_login"),
        "Your sign-in attempt expired. Please enter your email again.",
    )
    user_id = int(claims["sub"])
    is_setup = claims["typ"] == "mfa_setup"

    result = await db.execute(select(User).where(User.id == user_id))
    user = _check_account(result.scalar_one_or_none())

    if not user.mfa_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your authenticator was reset. Please enter your email again.",
        )
    if not is_setup and (user.auth_setup_required or not user.mfa_enabled):
        # Authenticator was reset after step 1: start again.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your authenticator was reset. Please enter your email again.",
        )

    _check_lockout(user.id)
    code = "".join(ch for ch in payload.code if ch.isdigit())
    if len(code) != 6 or not pyotp.TOTP(user.mfa_secret).verify(code, valid_window=1):
        _record_failure(user.id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That code didn't match. Check the 6-digit code in Google Authenticator and try again.",
        )
    _code_failures.pop(user.id, None)

    if is_setup:
        user.mfa_enabled = True
        user.auth_setup_required = False
        await log_event(
            db, user.id, HistoryEventType.AUTHENTICATOR_SETUP, description="Set up Google Authenticator"
        )

    await log_event(db, user.id, HistoryEventType.LOGIN, description="Signed in")
    await db.commit()
    await db.refresh(user)

    token = create_access_token(subject=str(user.id))
    return TokenOut(token=token, user=UserOut.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(current_user: User = Depends(get_current_user)):
    # Tokens are stateless; nothing to revoke server-side.
    return None


@router.get("/me", response_model=UserOut)
async def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user
