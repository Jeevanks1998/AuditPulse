"""
api/access_management.py

Phase 3 of the AuditPulse Access Portal integration (see
AuditPulse-Access/README.md). This is the endpoint
AuditPulse-Access/backend/auditpulse.py's sync_user()/revoke_user() call
once AUDITPULSE_BASE_URL is set on that side.

The portal is the source of truth for *who* has access and *what role*
they hold; this module's only job is to mirror that onto the matching
AuditPulse account (finding or creating it by email) so the rest of the
app — login, get_current_user, everything gated behind it — reflects
that decision without needing its own copy of the portal's users/roles
tables.

Phase 5 update: what the portal pushes for a user is now six fields
(see schemas/access.py's docstring for the full rationale) —

  - User.email               lookup/upsert key
  - User.name                display name
  - User.is_active            <- payload.active — Access Portal account
                              status in general, reused as the API-key
                              auth on/off flag (middleware/auth.py).
  - User.role                 a free-form label ("Admin"/"Auditor"/
                              "Reviewer"/"Viewer" today, whatever the
                              portal's roles.py defines tomorrow) —
                              AuditPulse doesn't interpret it, just
                              stores it and derives `permissions` from
                              it (models.user.User.permissions).
  - User.auditpulse_access    <- payload.auditpulse_access — whether this
                              person's role/assignment grants them
                              AuditPulse specifically, checked separately
                              from is_active by api/auth.py's login route.
  - permissions                not stored — computed from `role` on read
                              (config/permissions.py) and only ever
                              appears in this endpoint's *response*.
  - password_hash (optional)  <- payload.password_hash — bcrypt hash of
                              the temp password the portal issued on
                              create. Applied only when creating the
                              account (see sync_access() below); this is
                              what closes the previous gap where a
                              portal-synced account had no password
                              anyone actually knew.

Auth: every route here requires `Authorization: Bearer
<ACCESS_PORTAL_API_KEY>` (config/settings.py), a shared secret — *not* a
user JWT, since the portal isn't a logged-in AuditPulse user. There is
no open-by-default fallback: if ACCESS_PORTAL_API_KEY isn't set, every
call is rejected, because this endpoint can grant or remove app access.
"""

import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_password_hash, generate_api_key
from config.database import get_db
from config.logging import logger
from config.permissions import get_permissions
from config.settings import settings
from models.history import HistoryEventType, log_event
from models.user import User
from schemas.access import (
    AccessHealthOut,
    AccessRevokeIn,
    AccessRevokeOut,
    AccessSyncIn,
    AccessSyncOut,
)

router = APIRouter()


def verify_portal_key(authorization: Optional[str] = Header(None)) -> None:
    """Shared-secret check for every route in this module.

    Deliberately fails closed: an unconfigured ACCESS_PORTAL_API_KEY
    means "integration not set up yet", not "allow anything".
    """
    if not settings.ACCESS_PORTAL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Access Portal integration is not configured (ACCESS_PORTAL_API_KEY unset).",
        )

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(token, settings.ACCESS_PORTAL_API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access key.")


@router.get("/health", response_model=AccessHealthOut)
def health():
    """Unauthenticated on purpose: lets the portal's status page tell
    'AuditPulse unreachable' apart from 'reachable, but key not configured
    yet / wrong', without needing a valid key just to ask.
    """
    return AccessHealthOut(ok=True, configured=bool(settings.ACCESS_PORTAL_API_KEY))


@router.post("", response_model=AccessSyncOut, dependencies=[Depends(verify_portal_key)])
async def sync_access(payload: AccessSyncIn, db: AsyncSession = Depends(get_db)):
    """Upsert a user's name/role/access by email. Called on every
    create/update in the portal's users.py.
    """
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    created = False

    if user is None:
        created = True
        user = User(
            name=payload.name,
            email=payload.email,
            role=payload.role,
            is_active=payload.active,
            auditpulse_access=payload.auditpulse_access,
            # The portal sends the bcrypt hash of the temp password it
            # just issued to the new user (both sides use plain passlib
            # bcrypt, so the hash verifies here as-is) — this is what the
            # person actually logs in with on /auth/login. Fall back to
            # an unusable random hash only if an older portal build is
            # calling this without the field, so the NOT NULL column is
            # still satisfied and the account is simply unusable until a
            # real credential exists, rather than the request failing.
            hashed_password=payload.password_hash or get_password_hash(secrets.token_urlsafe(24)),
            api_key=generate_api_key(),
        )
        db.add(user)
        await db.flush()
    else:
        user.name = payload.name
        user.role = payload.role
        user.is_active = payload.active
        user.auditpulse_access = payload.auditpulse_access

    await log_event(
        db,
        user.id,
        HistoryEventType.ACCESS_SYNCED,
        description=(
            f"Access Portal set role={payload.role}, active={'yes' if payload.active else 'no'}, "
            f"auditpulse_access={'yes' if payload.auditpulse_access else 'no'}"
        ),
        meta={
            "portal_user_id": payload.user_id,
            "role": payload.role,
            "active": payload.active,
            "auditpulse_access": payload.auditpulse_access,
        },
    )
    await db.commit()
    await db.refresh(user)

    logger.info(
        f"Access Portal sync: {user.email} -> role={user.role}, active={user.is_active}, "
        f"auditpulse_access={user.auditpulse_access}"
    )
    return AccessSyncOut(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        permissions=get_permissions(user.role),
        is_active=user.is_active,
        auditpulse_access=user.auditpulse_access,
        created=created,
    )


@router.post("/revoke", response_model=AccessRevokeOut, dependencies=[Depends(verify_portal_key)])
async def revoke_access(payload: AccessRevokeIn, db: AsyncSession = Depends(get_db)):
    """Turn access off for a user the portal deleted entirely.

    Mirrors sync_access(active=False, auditpulse_access=False) rather than
    deleting the AuditPulse account outright — the account may own
    audits/reports/history that should survive even after the person
    loses access. If the portal never knew this email in the first place
    (nothing to revoke), this is a no-op that reports found=False rather
    than an error, since that's a normal outcome, not a failure of the
    call.
    """
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is None:
        return AccessRevokeOut(email=payload.email, found=False, is_active=False, auditpulse_access=False)

    user.is_active = False
    user.auditpulse_access = False
    await log_event(
        db, user.id, HistoryEventType.ACCESS_REVOKED, description="Access Portal revoked AuditPulse access"
    )
    await db.commit()

    logger.info(f"Access Portal revoke: {user.email} -> access off")
    return AccessRevokeOut(email=user.email, found=True, is_active=False, auditpulse_access=False)
