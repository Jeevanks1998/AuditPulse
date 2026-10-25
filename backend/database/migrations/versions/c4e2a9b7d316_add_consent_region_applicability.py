"""add consent region applicability, technical scan and control inventory

Revision ID: c4e2a9b7d316
Revises: f2a6c9d3e871
Create Date: 2026-10-01 00:00:00.000000

New consent_results columns: applicability, technical_scan, detected_region,
region_confidence, region_evidence, applicable_frameworks,
applicability_status and consent_controls. Existing rows get "UNKNOWN" /
"low" / "not_determined" / empty values.
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

    # server_default only fills existing rows; the model sets the default for new rows.
    with op.batch_alter_table("consent_results") as batch_op:
        for name in _JSON_OBJ + _JSON_LIST + ("detected_region", "region_confidence", "applicability_status"):
            batch_op.alter_column(name, server_default=None)


def downgrade() -> None:
    for name in ("applicability_status", "region_confidence", "detected_region") + _JSON_LIST + _JSON_OBJ:
        op.drop_column("consent_results", name)
