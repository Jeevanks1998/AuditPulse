"""
schemas/user.py

Request/response models for authentication (api/auth.py).

UserOut is also the shape the AuditPulse Access Portal integration hangs
off of (see api/access_management.py for Phase 3, config/permissions.py
for Phase 4, and this file's `role`/`permissions`/`auditpulse_access`
fields for Phase 5): every login/`me` response carries the portal-assigned
role, the module-permission map derived from it, and whether this specific
person currently has AuditPulse access — not just whether their account is
active — so the frontend (assets/js/permissions.js) can gate the UI off
the same session object the backend already enforces against.
"""

from typing import Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserLogin(BaseModel):
    """Step 1 of sign-in: just the email. No password — see api/auth.py."""

    email: EmailStr


class LoginStepOut(BaseModel):
    """Response to step 1. Tells the login page which screen to show next.

    step = "setup"   first login (or after an admin reset): show the QR code
                     so the person can add AuditPulse to Google Authenticator,
                     then ask for the 6-digit code it shows.
    step = "verify"  authenticator already paired: just ask for the code.

    challenge_token is a short-lived token (not a session) that only
    /auth/verify accepts. qr_code / secret / otpauth_uri are only set for
    step = "setup".
    """

    step: Literal["setup", "verify"]
    challenge_token: str
    email: EmailStr
    qr_code: Optional[str] = None  # data: URI of an SVG QR code
    secret: Optional[str] = None  # same key, for typing in manually
    otpauth_uri: Optional[str] = None


class TotpVerifyIn(BaseModel):
    """Step 2 of sign-in: the 6-digit Google Authenticator code."""

    challenge_token: str
    code: str = Field(min_length=6, max_length=8)


class UserRegister(BaseModel):
    """Not wired to a route — see api/auth.py's docstring: there is no
    /auth/register (or /auth/login-email); every account is provisioned by
    the Access Portal sync (api/access_management.py). Kept here only
    because utils/validators.py's docstring cross-references its field
    constraints (email shape) when validating those
    same values elsewhere in the app. Do not add a route that uses this to
    create a User — see api/auth.py before doing so.
    """

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
