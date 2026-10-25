"""add consent_results.gdpr_checks column

Revision ID: 9c3f2a7b5e14
Revises: 682b36c9a001
Create Date: 2026-09-09 00:00:00.000000

Stores the ten GDPR checks ({check: true/false/null}) so the report shows
which one failed. gdpr_compliant is kept. Defaults to empty.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "9c3f2a7b5e14"
down_revision: Union[str, None] = "682b36c9a001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "consent_results",
        sa.Column("gdpr_checks", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    # server_default only fills existing rows; the model sets the default for new rows.
    with op.batch_alter_table("consent_results") as batch_op:
        batch_op.alter_column("gdpr_checks", server_default=None)


def downgrade() -> None:
    op.drop_column("consent_results", "gdpr_checks")
