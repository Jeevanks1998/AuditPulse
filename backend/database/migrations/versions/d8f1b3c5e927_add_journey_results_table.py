"""add journey_results table (Customer Journey module)

Revision ID: d8f1b3c5e927
Revises: c4e2a9b7d316
Create Date: 2026-10-01 00:00:00.000000

One row per audit for the new "journey" module (journey/ package):
discovered pages and interactions, test outcomes with screenshot paths,
forms, downloads, the journey map, tracking validation and QA findings.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d8f1b3c5e927"
down_revision: Union[str, None] = "c4e2a9b7d316"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "journey_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("audit_id", sa.Integer(), sa.ForeignKey("audits.id", ondelete="CASCADE"), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("scan_id", sa.String(80), nullable=True),
        sa.Column("consent_state", sa.String(120), nullable=True),
        sa.Column("journey_score", sa.Integer(), nullable=True),
        sa.Column("health", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("pages", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("interactions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("forms", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("downloads", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("journey_map", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("tracking", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("findings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("limits", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("started_at", sa.String(40), nullable=True),
        sa.Column("finished_at", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_journey_results_audit_id", "journey_results", ["audit_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_journey_results_audit_id", table_name="journey_results")
    op.drop_table("journey_results")
