"""add users.role column

Revision ID: f1a9c6d2b834
Revises: e4312ce42c87
Create Date: 2026-09-12 00:00:00.000000

Phase 3 of the AuditPulse Access Portal integration: the portal is now
the source of truth for who has an "Admin" / "Auditor" / "Reviewer" /
"Viewer" role (see AuditPulse-Access/backend/roles.py's fixed four).
api/access_management.py writes this column whenever the portal syncs a
user; accounts that predate the portal (direct register/login-email)
default to "Viewer" so nothing that later checks `User.role` has to
special-case a null/missing value.

`is_active` already exists and is reused as the access on/off flag
(no new column needed for that — see api/access_management.py).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f1a9c6d2b834"
down_revision: Union[str, None] = "e4312ce42c87"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=40), nullable=False, server_default="Viewer"),
    )
    # server_default only exists to backfill pre-existing rows; the model
    # supplies the Python-side default for new rows going forward, same
    # convention as this codebase's other added columns.
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("role", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "role")
