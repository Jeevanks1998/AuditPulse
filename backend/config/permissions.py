"""
Which role can use which module, and a dependency that enforces it on routes.

MODULE_PERMISSIONS is a copy of PERMISSIONS in AuditPulse-Access/backend/roles.py
(the two apps are deployed separately). Update both together.
"""

from typing import Dict

from fastapi import Depends, HTTPException, status

# Role -> module -> allowed. "history" isn't gated: everyone sees their own activity.
MODULE_PERMISSIONS: Dict[str, Dict[str, bool]] = {
    "Admin":    {"dashboard": True, "audits": True,  "analytics": True, "reports": True, "scheduler": True,  "settings": True},
    "Auditor":  {"dashboard": True, "audits": True,  "analytics": True, "reports": True, "scheduler": True,  "settings": False},
    "Reviewer": {"dashboard": True, "audits": True,  "analytics": True, "reports": True, "scheduler": False, "settings": False},
    "Viewer":   {"dashboard": True, "audits": False, "analytics": True, "reports": True, "scheduler": False, "settings": False},
}

# Unknown roles get Viewer's (most restricted) permissions, never full access.
FALLBACK_ROLE = "Viewer"


def get_permissions(role: str) -> Dict[str, bool]:
    """Permissions for a role; unknown roles get Viewer's."""
    return MODULE_PERMISSIONS.get(role, MODULE_PERMISSIONS[FALLBACK_ROLE])


def require_module(module: str):
    """Use `Depends(require_module("scheduler"))` instead of get_current_user.
    401 if not signed in, 403 if the role lacks the module. This is the real
    check; hiding links in the frontend is only cosmetic.
    """
    # Imported here to avoid a circular import.
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
