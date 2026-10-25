"""
Sign-in and user models. UserOut includes the role, permissions and AuditPulse access the frontend uses.
"""

from typing import Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserLogin(BaseModel):
    """Sign-in step 1: email only."""

    email: EmailStr


class LoginStepOut(BaseModel):
    """Sign-in step 1 response: step "setup" (show QR code, then ask for the code)
    or "verify" (ask for the code). challenge_token only works for /auth/verify.
    qr_code / secret / otpauth_uri are only set for "setup".
    """

    step: Literal["setup", "verify"]
    challenge_token: str
    email: EmailStr
    qr_code: Optional[str] = None  # data: URI of an SVG QR code
    secret: Optional[str] = None  # same key, to type in manually
    otpauth_uri: Optional[str] = None


class TotpVerifyIn(BaseModel):
    """Sign-in step 2: the 6-digit code."""

    challenge_token: str
    code: str = Field(min_length=6, max_length=8)


class UserRegister(BaseModel):
    """Not used by any route. Accounts are only created by the Access Portal sync; don't add a sign-up route."""

    email: EmailStr
    name: str = Field(min_length=1, max_length=120)


class UserOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    company: str
    role: str
    permissions: Dict[str, bool]
    is_active: bool
    auditpulse_access: bool
    mfa_enabled: bool = False
    auth_setup_required: bool = True

    model_config = ConfigDict(from_attributes=True)


class TokenOut(BaseModel):
    token: str
    token_type: str = "bearer"
    user: UserOut
