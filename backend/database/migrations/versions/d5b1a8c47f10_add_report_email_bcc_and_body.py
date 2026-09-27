"""add report_emails.recipient_bcc and report_emails.body

Revision ID: d5b1a8c47f10
Revises: c9e7f3a1b562
Create Date: 2026-09-19 00:00:00.000000

Email History (§10) now has to store the *whole* send, not a summary of
it, because the Email Reports page's "Resend" action reopens the composer
with the previous email loaded — and a resend built from a row missing
its blind recipients or its body would quietly send a different email
than the one the user asked to repeat.

  - recipient_bcc: the blind recipients of that send. These are still
    kept out of the outgoing message's headers (emailer.service puts them
    in the SMTP envelope only); storing them here exposes them to the
    sender's own history and nobody else's.
  - body: the message text as actually sent, so a resend starts from what
    went out rather than regenerating emailer.templates' default.

Both default to empty ('[]' / '') and are NOT NULL, so rows written
before this migration read as "no bcc, body not recorded" — which is
exactly what they are — rather than as NULL holes the API has to guard.
A resend of one of those older rows falls back to the default template,
the same text that would have been generated for it originally.
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
