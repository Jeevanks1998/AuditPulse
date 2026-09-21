"""add analytics evidence columns (vendor_configs, page_results, site_coverage, cross_page_findings)

Revision ID: 682b36c9a001
Revises:
Create Date: 2026-08-16 00:00:00.000000

Adds the columns models.analytics.Analytics gained for the Analytics
Enhancement Plan (Phase 1.1 / Phase 2.2 / Phase 2.4):

  - vendor_configs: every detected vendor's actual configuration
    ({vendor_key: [ids]}) — Adobe report suites, Piano site IDs,
    Clarity/Hotjar site IDs, Meta Pixel/LinkedIn/TikTok IDs, plus the
    full GA4/GTM ID lists. Only vendors actually detected are present
    as keys — never a placeholder for an undetected vendor.
  - page_results: one entry per crawled page (serialized
    analytics.analytics_score.PageAnalyticsResult) for full-site audits.
  - site_coverage: analytics.analytics_score.compute_site_coverage's
    output (pages_scanned, pages_with_analytics, ...).
  - cross_page_findings: analytics.analytics_score.check_cross_page_consistency's
    output, kept separate from the page-level findings folded into
    Audit.findings so the report can render its own cross-page
    consistency section without re-filtering the full findings list.

All four default to an empty list/dict so a homepage-only audit (or a
row written before this migration) reads as "no full-site data"
rather than as a real audit that found zero pages/vendors.
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
    # server_default only exists to backfill pre-existing rows; the model
    # itself supplies the Python-side default for new rows going forward,
    # same convention as the table's other JSON columns.
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
