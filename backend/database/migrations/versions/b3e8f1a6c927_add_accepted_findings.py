"""add accepted_findings table and audits.raw_breakdown / raw_overall_score

Revision ID: b3e8f1a6c927
Revises: a7d3e9f1c204
Create Date: 2026-10-31 00:00:00.000000

Findings a site's team marks as intentional / accepted or "to be verified",
kept per website; and each audit's scores as measured before those were taken out.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b3e8f1a6c927"
down_revision: Union[str, None] = "a7d3e9f1c204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "accepted_findings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("website_id", sa.Integer(), sa.ForeignKey("websites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fingerprint", sa.String(length=400), nullable=False),
        sa.Column("module", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="accepted"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_by_name", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("website_id", "fingerprint", name="uq_accepted_findings_site_fp"),
    )
    op.create_index("ix_accepted_findings_website_id", "accepted_findings", ["website_id"])
    op.add_column("audits", sa.Column("raw_breakdown", sa.JSON(), nullable=True))
    op.add_column("audits", sa.Column("raw_overall_score", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("audits", "raw_overall_score")
    op.drop_column("audits", "raw_breakdown")
    op.drop_index("ix_accepted_findings_website_id", table_name="accepted_findings")
    op.drop_table("accepted_findings")
