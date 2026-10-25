"""
Request/response models for the Access Portal sync (api/access_management.py).
The portal sends `active` (account active at all) and `auditpulse_access`
(may use AuditPulse) separately. Permissions aren't sent; AuditPulse works
them out from the role.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AccessSyncIn(BaseModel):
    user_id: int  # the portal's own user id, only echoed back
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=40)
    active: bool
    auditpulse_access: bool
    # Set by the portal's "Reset Authenticator": the next login shows a new QR code.
    reset_authenticator: bool = False


class AccessRevokeIn(BaseModel):
    email: EmailStr


class AccessSyncOut(BaseModel):
    id: int
    email: EmailStr
    name: str
    role: str
    permissions: Dict[str, bool]
    is_active: bool
    auditpulse_access: bool
    mfa_enabled: bool = False
    auth_setup_required: bool = True
    created: bool  # True if this call created the account

    model_config = ConfigDict(from_attributes=True)


class AccessRevokeOut(BaseModel):
    email: EmailStr
    found: bool
    is_active: bool
    auditpulse_access: bool


class AccessStatusIn(BaseModel):
    """Emails to check sign-in status for (max 500)."""
    emails: List[EmailStr] = Field(default_factory=list, max_length=500)


class AccessUserStatus(BaseModel):
    exists: bool
    is_active: bool = False
    auditpulse_access: bool = False
    mfa_enabled: bool = False
    auth_setup_required: bool = True


class AccessStatusOut(BaseModel):
    users: Dict[str, AccessUserStatus]


class AccessHealthOut(BaseModel):
    ok: bool = True
    configured: bool
