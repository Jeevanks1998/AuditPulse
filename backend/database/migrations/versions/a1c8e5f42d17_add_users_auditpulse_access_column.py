"""add users.auditpulse_access column

Revision ID: a1c8e5f42d17
Revises: f1a9c6d2b834
Create Date: 2026-09-12 00:00:00.000000

AuditPulse access, separate from is_active. Existing users get True so no
one is locked out; the next portal sync sets the real value.
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
    # server_default only fills existing rows; the model sets the default for new rows.
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("auditpulse_access", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "auditpulse_access")
