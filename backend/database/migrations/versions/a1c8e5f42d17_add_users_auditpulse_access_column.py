"""add users.auditpulse_access column

Revision ID: a1c8e5f42d17
Revises: f1a9c6d2b834
Create Date: 2026-09-12 00:00:00.000000

Phase 5 of the AuditPulse Access Portal integration: the portal now
pushes AuditPulse-specific access (`auditpulse_access`) separately from
general account status (`is_active`) — see api/access_management.py and
schemas/access.py's docstrings for why they're two columns instead of
one. Existing rows backfill to True (mirrors the model's Python-side
default and today's Phase 3 behaviour, where is_active alone gated
access) so no currently-working account is locked out the moment this
migration runs; the very next Access Portal sync will set the real
per-user value going forward.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a1c8e5f42d17"
down_revision: Union[str, None] = "f1a9c6d2b834"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auditpulse_access", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    # server_default only exists to backfill pre-existing rows; the model
    # supplies the Python-side default for new rows going forward, same
    # convention as this codebase's other added columns (see
    # f1a9c6d2b834_add_users_role_column.py).
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("auditpulse_access", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "auditpulse_access")
