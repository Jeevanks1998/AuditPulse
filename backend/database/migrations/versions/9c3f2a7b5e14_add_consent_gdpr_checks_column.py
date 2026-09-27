"""add consent_results.gdpr_checks column

Revision ID: 9c3f2a7b5e14
Revises: 682b36c9a001
Create Date: 2026-09-09 00:00:00.000000

Phase 2 of the consent-detection rework: GDPR compliance is no longer a
single `gdpr_compliant` boolean — it's ten independently-testable checks
(consent banner, accept control, reject control, reject parity, trackers
blocked pre-consent, cookies blocked pre-consent, consent is granular,
privacy policy available, consent withdrawal available, reject actually
blocks tracking; see consent.consent_score.GDPR_CHECK_ORDER).

`gdpr_checks` stores that full breakdown ({check_key: true/false/null})
so a report can show exactly which requirement failed instead of only
the roll-up bit. `gdpr_compliant` is kept as-is (now derived from this
dict at write time via GdprAssessment.compliant) for any existing
code/dashboards that only care about the overall verdict.

Defaults to an empty dict so pre-existing rows read as "no per-check
breakdown available" rather than as a real audit that failed every
check.
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
    # server_default only exists to backfill pre-existing rows; the model
    # itself supplies the Python-side default for new rows going forward,
    # same convention as this table's other JSON columns.
    with op.batch_alter_table("consent_results") as batch_op:
        batch_op.alter_column("gdpr_checks", server_default=None)


def downgrade() -> None:
    op.drop_column("consent_results", "gdpr_checks")
