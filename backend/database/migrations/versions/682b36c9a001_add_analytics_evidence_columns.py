"""add analytics evidence columns (vendor_configs, page_results, site_coverage, cross_page_findings)

Revision ID: 682b36c9a001
Revises:
Create Date: 2026-08-16 00:00:00.000000

vendor_configs: IDs per detected tool. page_results / site_coverage /
cross_page_findings: full-site results. All default to empty.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "682b36c9a001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analytics_results",
        sa.Column("vendor_configs", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "analytics_results",
        sa.Column("page_results", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "analytics_results",
        sa.Column("site_coverage", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "analytics_results",
        sa.Column("cross_page_findings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    # server_default only fills existing rows; the model sets the default for new rows.
    with op.batch_alter_table("analytics_results") as batch_op:
        batch_op.alter_column("vendor_configs", server_default=None)
        batch_op.alter_column("page_results", server_default=None)
        batch_op.alter_column("site_coverage", server_default=None)
        batch_op.alter_column("cross_page_findings", server_default=None)


def downgrade() -> None:
    op.drop_column("analytics_results", "cross_page_findings")
    op.drop_column("analytics_results", "site_coverage")
    op.drop_column("analytics_results", "page_results")
    op.drop_column("analytics_results", "vendor_configs")
