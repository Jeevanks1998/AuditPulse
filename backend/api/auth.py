"""
api/auth.py

Authentication routes. The User model itself lives in models/user.py
(re-exported below so existing `from api.auth import User` imports across
the codebase keep working).

Sign-in is email -> Google Authenticator. There is no password:

    POST /auth/login   {email}
        Checks the account exists, is active and has AuditPulse access,
        then returns which screen to show next:
          - step "setup"  : first login, or the admin reset the
                            authenticator -> QR code to scan
          - step "verify" : authenticator already paired -> ask for code
        plus a short-lived challenge_token (NOT a session).

    POST /auth/verify  {challenge_token, code}
        Checks the 6-digit TOTP code. On a setup challenge this also
        marks the authenticator as configured (mfa_enabled = True,
        auth_setup_required = False). Returns the real session token.

The TOTP itself is plain RFC 6238 via pyotp — any authenticator app
works (Google Authenticator, Microsoft Authenticator, Authy, 1Password).
No Google API key or account is involved.

There is intentionally no /auth/register here — accounts are provisioned
exclusively by an administrator through the Access Portal sync
(api/access_management.py). See the note above the route definitions.

Also exposes `get_current_user`, the dependency every other router in
api/ uses to identify the caller.
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

# Name shown above the 6-digit code in Google Authenticator.
TOTP_ISSUER = "AuditPulse"

# Challenge tokens only bridge step 1 -> step 2 of login. Setup gets a bit
# longer because the person may need to install the app first.
CHALLENGE_TTL_MINUTES = {"mfa_setup": 15, "mfa_login": 5}

# Simple brute-force guard on the 6-digit code: after MAX_CODE_FAILURES
# wrong codes the account is locked out of code entry for
# CODE_LOCKOUT_SECONDS. In-process memory is enough for a single Railway
# instance; the /auth/* rate limiter (middleware/rate_limit.py) still
# applies on top of this.
MAX_CODE_FAILURES = 5
CODE_LOCKOUT_SECONDS = 5 * 60
_code_failures: Dict[int, Tuple[int, float]] = {}

# auto_error=False so an unauthenticated request reaches get_current_user and
# gets a clean 401 with a WWW-Authenticate header, rather than FastAPI's
# generic "Not authenticated" from the security dependency itself.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login", auto_error=False
)


# --------------------------------------------------------------------------
# Token helpers
# --------------------------------------------------------------------------
def generate_api_key() -> str:
    """ap_live_<20 hex chars> — matches the shape seeded in the frontend mock db."""
    return "ap_live_" + secrets.token_hex(10)


def _encode(subject: str, typ: str, expires_minutes: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload = {"sub": subject, "typ": typ, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(subject: str, expires_minutes: Optional[int] = None) -> str:
    """A real session. Only ever issued after a correct authenticator code."""
    return _encode(subject, "access", expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)


def create_challenge_token(subject: str, typ: str) -> str:
    """Bridges /auth/login -> /auth/verify. Rejected everywhere else."""
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
    # Only "access" tokens are sessions. Challenge tokens, and tokens
    # issued by the old password login (no "typ"), are refused — so
    # everyone signs in through the authenticator after this deploy.
    return _decode(token, ("access",), "Could not validate credentials")["sub"]


# --------------------------------------------------------------------------
# TOTP helpers
# --------------------------------------------------------------------------
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
    """The same account checks for both login steps, so an account that is
    disabled between step 1 and step 2 can't finish signing in."""
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
    if not user.mfa_enabled or user.auth_setup_required:
        # The admin reset this person's authenticator after the session was
        # issued — end the session so they set up the new one at login.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your authenticator was reset. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# --------------------------------------------------------------------------
# Routes
#
# Deliberately just four: login, verify, logout, me. There is no self-service
# /auth/register (and no /auth/login-email — see git history) — every
# AuditPulse account must already exist, created and activated by an
# administrator via the Access Portal sync (api/access_management.py).
# None of the routes below may create a User row; if you're tempted to
# add "if user doesn't exist: create it" anywhere in this file, don't —
# account creation only ever happens in api/access_management.py.
# --------------------------------------------------------------------------


@router.post("/login", response_model=LoginStepOut)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    """Step 1 — email only. Checked in order, no account ever created here:

      1. Does the account exist?           -> 401
      2. Is the account active?            -> "Your account is inactive"
      3. Does it have AuditPulse access?   -> "You don't have AuditPulse access"
      4. Is the authenticator configured?
            no  -> step "setup"  (new secret + QR code)
            yes -> step "verify" (ask for the 6-digit code)
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

    # First-time setup (or after an admin reset): issue a fresh secret.
    # It is saved now but mfa_enabled stays False until the person proves
    # they scanned it by entering a correct code in /auth/verify.
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
    """Step 2 — the 6-digit Google Authenticator code. Returns the session."""
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
        # Admin reset the authenticator after step 1 — start over with setup.
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
    # Stateless JWTs: nothing to invalidate server-side. If you need
    # server-side revocation later, blocklist the token's jti in Redis here.
    return None


@router.get("/me", response_model=UserOut)
async def read_current_user(current_user: User = Depends(get_current_user)):
    return current_user
