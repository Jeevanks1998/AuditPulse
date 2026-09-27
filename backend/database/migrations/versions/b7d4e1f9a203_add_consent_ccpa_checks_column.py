"""add consent_results.ccpa_checks column

Revision ID: b7d4e1f9a203
Revises: 9c3f2a7b5e14
Create Date: 2026-09-09 00:00:00.000000

CCPA counterpart to the gdpr_checks column added in 9c3f2a7b5e14: CCPA
compliance is no longer a single `ccpa_compliant` boolean (a hand-rolled
`ccpa_link_found and privacy_policy_url is not None`) — it's six
independently-testable checks (privacy policy available, "Your Privacy
Choices" link, "Do Not Sell or Share" link, opt-out mechanism reachable,
Global Privacy Control signal handling, opt-out actually stops tracking;
see consent.consent_score.CCPA_CHECK_ORDER).

`ccpa_checks` stores that full breakdown ({check_key: true/false/null})
so a report can show exactly which requirement failed instead of only
the roll-up bit. `ccpa_compliant` is kept as-is (now derived from this
dict at write time via CcpaAssessment.compliant) for any existing
code/dashboards that only care about the overall verdict.

Defaults to an empty dict so pre-existing rows read as "no per-check
breakdown available" rather than as a real audit that failed every
check.
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
    # server_default only exists to backfill pre-existing rows; the model
    # itself supplies the Python-side default for new rows going forward,
    # same convention as this table's other JSON columns.
    with op.batch_alter_table("consent_results") as batch_op:
        batch_op.alter_column("ccpa_checks", server_default=None)


def downgrade() -> None:
    op.drop_column("consent_results", "ccpa_checks")
