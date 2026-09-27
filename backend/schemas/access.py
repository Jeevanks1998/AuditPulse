"""
schemas/access.py

Request/response models for api/access_management.py — the internal
endpoint the AuditPulse Access Portal calls to push a user's role and
access status.

Phase 5 of the integration: the portal pushes the account status
(`active`) and AuditPulse-specific access (`auditpulse_access`) as two
separate booleans instead of one combined `access` flag, because they
answer different questions —

    active              is this person's Access Portal account active at
                         all (any app, not just this one)?
    auditpulse_access    does their current role/assignment grant them
                         AuditPulse specifically?

A user can be `active: true` in the portal (e.g. still has access to
other portal-managed apps) while `auditpulse_access: false`, and
api/auth.py's login route must reject that case with a message distinct
from "account inactive". `permissions` isn't part of the payload: it's
derived on this side, per role, from config/permissions.py's copy of the
portal's own role matrix (see that module's docstring for why it's a
copy rather than a shared import) and only ever appears in the *response*
(AccessSyncOut / schemas.user.UserOut), never sent by the portal.

NOTE: the portal-side payload builder (AuditPulse-Access/backend/
auditpulse.py's sync_user()/revoke_user()) must be updated to send
`active`/`auditpulse_access` instead of the old single `access` field —
that's a change to the sibling repo, not this one.
"""

from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AccessSyncIn(BaseModel):
    user_id: int  # the Access Portal's own id for this user, echoed back only
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=40)
    active: bool
    auditpulse_access: bool
    # Optional bcrypt hash of the temp password the portal just issued
    # (AuditPulse-Access/backend/users.py, on create only). Both sides
    # hash with plain passlib bcrypt, so this verifies directly against
    # AuditPulse's own login route — see access_management.py for how
    # it's used, and why it's only applied when creating the account.
    password_hash: Optional[str] = None


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
    created: bool  # True if this call created the AuditPulse account

    model_config = ConfigDict(from_attributes=True)


class AccessRevokeOut(BaseModel):
    email: EmailStr
    found: bool
    is_active: bool
    auditpulse_access: bool


class AccessHealthOut(BaseModel):
    ok: bool = True
    configured: bool
