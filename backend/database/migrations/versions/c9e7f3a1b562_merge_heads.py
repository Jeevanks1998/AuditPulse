"""merge heads

Revision ID: c9e7f3a1b562
Revises: a1c8e5f42d17, b7d4e1f9a203
Create Date: 2026-09-13 00:00:00.000000

Joins two separate migration chains into one, so `alembic upgrade head`
works. No schema changes.
"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "c9e7f3a1b562"
down_revision: Union[str, Sequence[str], None] = ("a1c8e5f42d17", "b7d4e1f9a203")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass