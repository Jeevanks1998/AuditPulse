"""add per-audit target_region to audits

Revision ID: a4d2e8c6f913
Revises: e7a3c1f9b246
Create Date: 2026-10-02 12:00:00.000000

Optional privacy region chosen when starting an audit ("EU" | "UK" |
"US-CA" | "IN"). NULL keeps automatic detection (consent/region.py).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a4d2e8c6f913"
down_revision: Union[str, None] = "e7a3c1f9b246"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE audits ADD COLUMN IF NOT EXISTS target_region VARCHAR(10)")


def downgrade() -> None:
    op.execute("ALTER TABLE audits DROP COLUMN IF EXISTS target_region")
