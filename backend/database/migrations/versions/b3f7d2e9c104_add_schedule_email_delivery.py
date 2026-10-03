"""add schedule email delivery + audits.schedule_id

Revision ID: b3f7d2e9c104
Revises: a4d2e8c6f913
Create Date: 2026-10-03 00:00:00.000000

  - schedules.email_delivery (JSON, nullable): who gets the report after
    each scheduled run and which attachments go with it —
    {"enabled": true, "to": [...], "cc": [...], "attachments": ["pdf"],
     "subject": null, "message": null} plus the last delivery result
    (last_status / last_sent_at / last_error / last_audit_id).
  - audits.schedule_id (Integer, nullable, indexed): the schedule that
    fired this audit, so the pipeline knows to email the report when the
    run completes. Plain integer (no FK) so deleting a schedule never
    touches audit history.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b3f7d2e9c104"
down_revision: Union[str, None] = "a4d2e8c6f913"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schedules", sa.Column("email_delivery", sa.JSON(), nullable=True))
    op.add_column("audits", sa.Column("schedule_id", sa.Integer(), nullable=True))
    op.create_index("ix_audits_schedule_id", "audits", ["schedule_id"])


def downgrade() -> None:
    op.drop_index("ix_audits_schedule_id", table_name="audits")
    op.drop_column("audits", "schedule_id")
    op.drop_column("schedules", "email_delivery")
