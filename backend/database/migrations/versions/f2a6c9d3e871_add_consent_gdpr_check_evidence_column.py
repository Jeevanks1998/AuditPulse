"""add consent_results region detection columns

Revision ID: 7b2d9a4c6e35
Revises: f2a6c9d3e871
Create Date: 2026-09-26 00:00:00.000000

Adds columns for consent.region_detector.detect_region's output —
detected_region, detected_country, compliance_framework,
region_confidence, region_detection_source, region_detection_reason —
plus gdpr_assessed/ccpa_assessed, which previously only existed on the
in-memory consent.consent_score.ConsentSummary dataclass (see the
migration note on its gdpr_compliant/ccpa_compliant fields) and were
never persisted.

Before this, gdpr_compliant/ccpa_compliant being non-nullable booleans
meant "not applicable to this region" and "failed" were both stored as
False — indistinguishable on the history page. gdpr_assessed/
ccpa_assessed fix that without touching those two existing columns:
False here now unambiguously means "not assessed", and the detection
columns let the history page show *why* (which region/country was
detected, from which signal, at what confidence) instead of just a
blank framework.

All columns are non-nullable with a server_default so existing rows
backfill as "no region detected" (matching
consent.consent_score.REGION_UNKNOWN / RegionDetectionResult's own
"no signals" result) rather than leaving nulls the ORM's Python-side
defaults wouldn't apply to pre-existing rows, except
detected_country/compliance_framework, which are nullable — both are
genuinely absent (no specific country pinned down, no framework in
scope) for plenty of legitimate audits, not just "not backfilled yet".
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "7b2d9a4c6e35"
down_revision: Union[str, None] = "f2a6c9d3e871"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "consent_results",
        sa.Column("detected_region", sa.String(length=20), nullable=False, server_default="UNKNOWN"),
    )
    op.add_column(
        "consent_results",
        sa.Column("detected_country", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "consent_results",
        sa.Column("compliance_framework", sa.String(length=30), nullable=True),
    )
    op.add_column(
        "consent_results",
        sa.Column("region_confidence", sa.String(length=10), nullable=False, server_default="none"),
    )
    op.add_column(
        "consent_results",
        sa.Column("region_detection_source", sa.String(length=200), nullable=False, server_default="None"),
    )
    op.add_column(
        "consent_results",
        sa.Column("region_detection_reason", sa.String(length=1000), nullable=False, server_default=""),
    )
    op.add_column(
        "consent_results",
        sa.Column("gdpr_assessed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "consent_results",
        sa.Column("ccpa_assessed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # server_default above only exists to backfill pre-existing rows; the
    # model itself supplies the Python-side default for new rows going
    # forward, same convention as this table's other non-nullable columns
    # added after the initial table (see f2a6c9d3e871).
    with op.batch_alter_table("consent_results") as batch_op:
        batch_op.alter_column("detected_region", server_default=None)
        batch_op.alter_column("region_confidence", server_default=None)
        batch_op.alter_column("region_detection_source", server_default=None)
        batch_op.alter_column("region_detection_reason", server_default=None)
        batch_op.alter_column("gdpr_assessed", server_default=None)
        batch_op.alter_column("ccpa_assessed", server_default=None)


def downgrade() -> None:
    op.drop_column("consent_results", "ccpa_assessed")
    op.drop_column("consent_results", "gdpr_assessed")
    op.drop_column("consent_results", "region_detection_reason")
    op.drop_column("consent_results", "region_detection_source")
    op.drop_column("consent_results", "region_confidence")
    op.drop_column("consent_results", "compliance_framework")
    op.drop_column("consent_results", "detected_country")
    op.drop_column("consent_results", "detected_region")
