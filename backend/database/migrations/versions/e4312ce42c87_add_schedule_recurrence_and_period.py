"""add schedule recurrence detail and schedule_period columns

Revision ID: e4312ce42c87
Revises:
Create Date: 2026-09-11 00:00:00.000000

Adds two JSON columns to `schedules` (services.scheduler_service.Schedule),
introduced for the redesigned Schedule Audit modal:

  - schedule: structured recurrence detail behind `frequency`/`time_label`
    (e.g. {"time": "09:00 AM", "timezone": "Asia/Kolkata", "weekday":
    "Monday"} for Weekly, or {"year_month": "September", "year_day": 15,
    "time": "09:00 AM"} for Yearly). `frequency` also now accepts "Yearly".
  - schedule_period: the window during which the recurring schedule is
    active — {"start_date": "2026-09-10", "end_date": "2027-09-10",
    "never_expires": false} — distinct from `frequency`/`schedule`, which
    control how often it repeats, not how long it stays active.

Both are nullable; existing rows read as "no structured detail", falling
back to `frequency`/`time_label` for display.
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
