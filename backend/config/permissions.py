"""
config/permissions.py

Phase 4 of the AuditPulse Access Portal integration (see
AuditPulse-Access/README.md and api/access_management.py for Phase 3).

Phase 3 made AuditPulse *store* the role the Access Portal assigns
(`User.role`). This module is what makes AuditPulse actually *read* it:
a role -> module permission matrix, plus a FastAPI dependency that gates
a route on it.

MODULE_PERMISSIONS is a deliberate copy of AuditPulse-Access/backend/
roles.py's `PERMISSIONS` dict, not an import of it — the two are separate
deployments (this backend has no dependency on the portal's repo/runtime),
so the portal stays the single *authored* source of truth for what each
role can do, and this is AuditPulse's own copy of that same decision.
If a role is ever added or a module's access changes, update both.

Kept deliberately dumb, matching roles.py's own comment: a plain dict,
no `permissions` table, no per-organisation overrides. Add those to both
sides together if a customer ever needs a role's access customised.
"""

from typing import Dict

from fastapi import Depends, HTTPException, status

# Module -> allowed, per role name. Same four fixed roles and six modules
# as AuditPulse-Access/backend/roles.py's PERMISSIONS. "history" isn't a
# gated module here either, on purpose (see that file's comment) — every
# role can see their own activity log.
MODULE_PERMISSIONS: Dict[str, Dict[str, bool]] = {
    "Admin":    {"dashboard": True, "audits": True,  "analytics": True, "reports": True, "scheduler": True,  "settings": True},
    "Auditor":  {"dashboard": True, "audits": True,  "analytics": True, "reports": True, "scheduler": True,  "settings": False},
    "Reviewer": {"dashboard": True, "audits": True,  "analytics": True, "reports": True, "scheduler": False, "settings": False},
    "Viewer":   {"dashboard": True, "audits": False, "analytics": True, "reports": True, "scheduler": False, "settings": False},
}

# Any role not in the dict above (shouldn't happen once Phase 3's
# migration backfills "Viewer", but a hand-edited row or a future role
# the portal defines that this copy hasn't caught up with yet is
# possible) gets the least-privileged existing role's permissions rather
# than a KeyError or, worse, defaulting to allow-everything.
FALLBACK_ROLE = "Viewer"


def get_permissions(role: str) -> Dict[str, bool]:
    """Module access dict for a role name. Never raises — an unknown role
    just falls back to Viewer's (most restrictive) permissions."""
    return MODULE_PERMISSIONS.get(role, MODULE_PERMISSIONS[FALLBACK_ROLE])


def require_module(module: str):
    """Dependency factory: `Depends(require_module("scheduler"))` in place
    of `Depends(get_current_user)` on a route. Resolves the current user
    exactly as before (still 401s if unauthenticated) and additionally
    403s if that user's role doesn't have `module` enabled.

    This is the real enforcement — the frontend hiding a sidebar link or
    redirecting away from a page (assets/js/permissions.js) is only the
    UX layer on top of it, never a substitute for it, since a hidden
    button doesn't stop a direct API call.
    """
    # Imported inside the factory, not at module load, to avoid a circular
    # import: api/auth.py doesn't import this module, but several routers
    # that *do* import this module (api/audit.py, api/scheduler.py,
    # api/settings.py) already import get_current_user from api.auth
    # too, so this keeps the import graph a simple one-way dependency on
    # api.auth rather than a cycle through it.
    from api.auth import User, get_current_user

    async def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if not get_permissions(current_user.role).get(module, False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Your role ({current_user.role}) doesn't have access "
                    f"to {module}. Ask an org admin to change your role in "
                    "the Access Portal if this is wrong."
                ),
            )
        return current_user

    return _dependency
