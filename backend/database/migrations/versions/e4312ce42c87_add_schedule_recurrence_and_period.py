"""add schedule recurrence detail and schedule_period columns

Revision ID: e4312ce42c87
Revises:
Create Date: 2026-09-11 00:00:00.000000

schedules.schedule: recurrence details, e.g. {"time": "09:00 AM",
"timezone": "Asia/Kolkata", "weekday": "Monday"}. frequency also allows "Yearly".
schedules.schedule_period: when it's active, e.g. {"start_date",
"end_date", "never_expires"}. Both nullable.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e4312ce42c87"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schedules", sa.Column("schedule", sa.JSON(), nullable=True))
    op.add_column("schedules", sa.Column("schedule_period", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("schedules", "schedule_period")
    op.drop_column("schedules", "schedule")
