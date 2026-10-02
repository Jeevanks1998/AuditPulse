"""add consent region applicability, technical scan and control inventory

Revision ID: c4e2a9b7d316
Revises: f2a6c9d3e871
Create Date: 2026-10-01 00:00:00.000000

Phases 1–3 of evidence-based consent scanning, in one migration:

  applicability          JSON  full region-engine output + which frameworks
                               were assessed (consent.region.RegionResult)
  technical_scan         JSON  framework-neutral technical consent scan:
                               rendered banner, control inventory, technical
                               checks, classified network/cookie evidence,
                               fresh-scan metadata (scan_id, pipeline steps)
  detected_region        str   "IN" / "EU" / "UK" / "US-CA" / "UNKNOWN"
  region_confidence      str   high / medium / low
  region_evidence        JSON  ["…domain", "GDPR reference", …]
  applicable_frameworks  JSON  ["gdpr"] / ["ccpa"] / ["dpdp"] / []
  applicability_status   str   determined / not_determined
  consent_controls       JSON  [{"label": "Accept all", "action": "accept_all"}, …]

gdpr_checks / ccpa_checks are now only filled when that framework applies.
The historical migrations 9c3f2a7b5e14 / b7d4e1f9a203 are not modified.
Pre-existing rows get "UNKNOWN" / "low" / "not_determined" / empty lists,
and the report shows its legacy view for them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c4e2a9b7d316"
down_revision: Union[str, None] = "f2a6c9d3e871"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON_OBJ = ("applicability", "technical_scan")
_JSON_LIST = ("region_evidence", "applicable_frameworks", "consent_controls")


def upgrade() -> None:
    for name in _JSON_OBJ:
        op.add_column("consent_results", sa.Column(name, sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    for name in _JSON_LIST:
        op.add_column("consent_results", sa.Column(name, sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("consent_results", sa.Column("detected_region", sa.String(16), nullable=False,
                                               server_default="UNKNOWN"))
    op.add_column("consent_results", sa.Column("region_confidence", sa.String(16), nullable=False,
                                               server_default="low"))
    op.add_column("consent_results", sa.Column("applicability_status", sa.String(32), nullable=False,
                                               server_default="not_determined"))

    # server_default only backfills existing rows; the model supplies
    # Python-side defaults for new rows (same convention as other columns).
    with op.batch_alter_table("consent_results") as batch_op:
        for name in _JSON_OBJ + _JSON_LIST + ("detected_region", "region_confidence", "applicability_status"):
            batch_op.alter_column(name, server_default=None)


def downgrade() -> None:
    for name in ("applicability_status", "region_confidence", "detected_region") + _JSON_LIST + _JSON_OBJ:
        op.drop_column("consent_results", name)
