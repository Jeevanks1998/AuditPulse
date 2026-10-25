"""add consent_results.ccpa_checks column

Revision ID: b7d4e1f9a203
Revises: 9c3f2a7b5e14
Create Date: 2026-09-09 00:00:00.000000

Stores the six CCPA checks ({check: true/false/null}). ccpa_compliant is
kept. Defaults to empty.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b7d4e1f9a203"
down_revision: Union[str, None] = "9c3f2a7b5e14"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "consent_results",
        sa.Column("ccpa_checks", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    # server_default only fills existing rows; the model sets the default for new rows.
    with op.batch_alter_table("consent_results") as batch_op:
        batch_op.alter_column("ccpa_checks", server_default=None)


def downgrade() -> None:
    op.drop_column("consent_results", "ccpa_checks")
