"""add consent_results.gdpr_check_evidence column

Revision ID: f2a6c9d3e871
Revises: d5b1a8c47f10
Create Date: 2026-09-20 00:00:00.000000

Evidence explaining why a GDPR check failed (e.g. the tracking requests seen
before consent). Only checks with evidence appear. Defaults to empty.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f2a6c9d3e871"
down_revision: Union[str, None] = "d5b1a8c47f10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "consent_results",
        sa.Column("gdpr_check_evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    # server_default only fills existing rows; the model sets the default for new rows.
    with op.batch_alter_table("consent_results") as batch_op:
        batch_op.alter_column("gdpr_check_evidence", server_default=None)


def downgrade() -> None:
    op.drop_column("consent_results", "gdpr_check_evidence")
