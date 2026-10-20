"""add audits.deleted_at (soft delete with restore)

Revision ID: a7d3e9f1c204
Revises: c9e4a2f7d158
Create Date: 2026-10-20 00:00:00.000000

Deleting an audit from History / Recent Audits now only sets deleted_at:
the audit and its report stay in the database and can be restored from
"Deleted audits". NULL = not deleted, so every existing row stays visible.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a7d3e9f1c204"
down_revision: Union[str, None] = "c9e4a2f7d158"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audits", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_audits_deleted_at", "audits", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_audits_deleted_at", table_name="audits")
    op.drop_column("audits", "deleted_at")
