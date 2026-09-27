"""add consent_results.gdpr_check_evidence column

Revision ID: f2a6c9d3e871
Revises: d5b1a8c47f10
Create Date: 2026-09-20 00:00:00.000000

Companion to the gdpr_checks column added in 9c3f2a7b5e14: gdpr_checks only
ever stored the pass/fail/not-evaluated bit for each of the ten GDPR
checks, with no way to show *why* a failed check failed beyond the fixed
label text. `gdpr_check_evidence` stores real, structured evidence for
whichever checks have it (currently just trackers_blocked_pre_consent,
backed by consent.network's live pre-consent request capture — the same
data the flat "N request(s) to known tracker(s) (...) were observed
before any consent action" finding text and the PDF export already draw
on, now exposed per-check instead of only as a flat finding).

Sparse by design: most checks have no extra evidence beyond their label
and pass/fail bit, so only keys with real evidence appear here. Defaults
to an empty dict so pre-existing rows read as "no evidence recorded"
rather than as a real audit with a passing/failing evidence set.
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
    # server_default only exists to backfill pre-existing rows; the model
    # itself supplies the Python-side default for new rows going forward,
    # same convention as this table's other JSON columns.
    with op.batch_alter_table("consent_results") as batch_op:
        batch_op.alter_column("gdpr_check_evidence", server_default=None)


def downgrade() -> None:
    op.drop_column("consent_results", "gdpr_check_evidence")
