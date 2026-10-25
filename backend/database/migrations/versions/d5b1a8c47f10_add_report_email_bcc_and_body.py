"""add report_emails.recipient_bcc and report_emails.body

Revision ID: d5b1a8c47f10
Revises: c9e7f3a1b562
Create Date: 2026-09-19 00:00:00.000000

Email history stores the full email so "Resend" sends exactly the same one:
recipient_bcc (only visible in the sender's own history) and body.
Older rows get empty values and fall back to the default template.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5b1a8c47f10"
down_revision: Union[str, None] = "c9e7f3a1b562"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "report_emails",
        sa.Column("recipient_bcc", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "report_emails",
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("report_emails", "body")
    op.drop_column("report_emails", "recipient_bcc")
