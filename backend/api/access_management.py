"""
Endpoints the Access Portal calls to sync users into AuditPulse.

The portal decides who has access and with which role; this mirrors that
onto the AuditPulse account (found or created by email):
  name, role, is_active, auditpulse_access, and reset_authenticator
  (clears the authenticator so the next login shows a new QR code).
Permissions are worked out from the role, not stored. No passwords: sign-in
is email + Google Authenticator.

Every route needs `Authorization: Bearer <ACCESS_PORTAL_API_KEY>`. If the key
isn't set, every call is refused.
"""

import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import generate_api_key
from config.database import get_db
from config.logging import logger
from config.permissions import get_permissions
from config.settings import settings
from models.history import HistoryEventType, log_event
from models.user import User
from schemas.access import (
    AccessHealthOut,
    AccessStatusIn,
    AccessStatusOut,
    AccessUserStatus,
    AccessRevokeIn,
    AccessRevokeOut,
    AccessSyncIn,
    AccessSyncOut,
)

router = APIRouter()


def verify_portal_key(authorization: Optional[str] = Header(None)) -> None:
    """Checks the shared key. No key configured means refuse, not allow."""
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
    """No key needed, so the portal can tell "unreachable" from "wrong key"."""
    return AccessHealthOut(ok=True, configured=bool(settings.ACCESS_PORTAL_API_KEY))


@router.post("", response_model=AccessSyncOut, dependencies=[Depends(verify_portal_key)])
async def sync_access(payload: AccessSyncIn, db: AsyncSession = Depends(get_db)):
    """Creates or updates a user's name/role/access by email."""
    result = await db.execute(select(User).where(func.lower(User.email) == payload.email.lower()))
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
            # No password: the person sets up Google Authenticator at first sign-in.
            hashed_password=None,
            mfa_secret=None,
            mfa_enabled=False,
            auth_setup_required=True,
            api_key=generate_api_key(),
        )
        db.add(user)
        await db.flush()
    else:
        user.name = payload.name
        user.role = payload.role
        user.is_active = payload.active
        user.auditpulse_access = payload.auditpulse_access

    if payload.reset_authenticator and not created:
        user.mfa_secret = None
        user.mfa_enabled = False
        user.auth_setup_required = True
        await log_event(
            db,
            user.id,
            HistoryEventType.AUTHENTICATOR_RESET,
            description="Access Portal admin reset the Google Authenticator",
        )

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
        + (", authenticator reset" if payload.reset_authenticator else "")
    )
    return AccessSyncOut(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        permissions=get_permissions(user.role),
        is_active=user.is_active,
        auditpulse_access=user.auditpulse_access,
        mfa_enabled=user.mfa_enabled,
        auth_setup_required=user.auth_setup_required,
        created=created,
    )


@router.post("/revoke", response_model=AccessRevokeOut, dependencies=[Depends(verify_portal_key)])
async def revoke_access(payload: AccessRevokeIn, db: AsyncSession = Depends(get_db)):
    """Turns access off for a user deleted in the portal. The account is kept (it
    may own audits). An unknown email is not an error: found=False.
    """
    result = await db.execute(select(User).where(func.lower(User.email) == payload.email.lower()))
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


@router.post("/status", response_model=AccessStatusOut, dependencies=[Depends(verify_portal_key)])
async def access_status(payload: AccessStatusIn, db: AsyncSession = Depends(get_db)):
    """Whether each email has finished AuditPulse authenticator setup (for the portal's Users page). POST keeps emails out of URLs."""
    emails = sorted({e.lower() for e in payload.emails})
    found = {}
    if emails:
        result = await db.execute(select(User).where(func.lower(User.email).in_(emails)))
        for u in result.scalars().all():
            found[u.email.lower()] = u
    users = {}
    for email in emails:
        u = found.get(email)
        users[email] = AccessUserStatus(
            exists=u is not None,
            is_active=bool(u and u.is_active),
            auditpulse_access=bool(u and u.auditpulse_access),
            mfa_enabled=bool(u and u.mfa_enabled),
            auth_setup_required=bool(u.auth_setup_required) if u else True,
        )
    return AccessStatusOut(users=users)
