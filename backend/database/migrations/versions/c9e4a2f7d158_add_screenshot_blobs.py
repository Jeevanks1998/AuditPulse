"""add screenshot_blobs (durable evidence screenshots)

Revision ID: c9e4a2f7d158
Revises: b3f7d2e9c104
Create Date: 2026-10-04 00:00:00.000000

Evidence screenshots were only on the container's local disk, which
Railway wipes on every redeploy (and which a separate worker service
doesn't share), so reports lost their consent and Journey Map screenshots.
This table keeps a compact JPEG copy keyed by the path after
"/screenshots/" in the stored URL; main.py serves from it when the file
isn't on disk.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c9e4a2f7d158"
down_revision: Union[str, None] = "b3f7d2e9c104"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "screenshot_blobs",
        sa.Column("key", sa.String(length=512), primary_key=True),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_type", sa.String(length=40), nullable=False, server_default="image/jpeg"),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_screenshot_blobs_created_at", "screenshot_blobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_screenshot_blobs_created_at", table_name="screenshot_blobs")
    op.drop_table("screenshot_blobs")
