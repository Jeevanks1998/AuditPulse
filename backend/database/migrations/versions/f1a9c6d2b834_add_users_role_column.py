"""add users.role column

Revision ID: f1a9c6d2b834
Revises: e4312ce42c87
Create Date: 2026-09-12 00:00:00.000000

Role set by the Access Portal ("Admin" / "Auditor" / "Reviewer" / "Viewer").
Existing users default to "Viewer".
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
    # server_default only fills existing rows; the model sets the default for new rows.
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("role", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "role")
