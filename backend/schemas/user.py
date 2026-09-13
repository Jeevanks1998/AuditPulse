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

from typing import Dict

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class UserRegister(BaseModel):
    """Not wired to a route — see api/auth.py's docstring: there is no
    /auth/register (or /auth/login-email); every account is provisioned by
    the Access Portal sync (api/access_management.py). Kept here only
    because utils/validators.py's docstring cross-references its field
    constraints (email shape, password min_length) when validating those
    same values elsewhere in the app. Do not add a route that uses this to
    create a User — see api/auth.py before doing so.
    """

    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=6)


class UserOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    company: str
    role: str
    permissions: Dict[str, bool]
    is_active: bool
    auditpulse_access: bool

    model_config = ConfigDict(from_attributes=True)


class TokenOut(BaseModel):
    token: str
    token_type: str = "bearer"
    user: UserOut
