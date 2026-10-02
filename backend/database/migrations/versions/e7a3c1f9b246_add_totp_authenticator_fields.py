"""add Google Authenticator (TOTP) sign-in fields to users

Revision ID: e7a3c1f9b246
Revises: d8f1b3c5e927
Create Date: 2026-10-02 00:00:00.000000

Sign-in changes from email + password to email -> Google Authenticator:

  - users.mfa_secret            base32 TOTP secret (NULL until set up)
  - users.mfa_enabled           TRUE once the user has paired an authenticator
  - users.auth_setup_required   TRUE means the next login shows the QR setup

Every existing user starts with mfa_enabled = FALSE and
auth_setup_required = TRUE, so they are asked to scan a QR code the
first time they sign in after this deploy.

users.hashed_password becomes nullable: passwords are no longer used,
and users created by the Access Portal from now on have none. The column
is kept (not dropped) so this migration is safe to roll back.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e7a3c1f9b246"
down_revision: Union[str, None] = "d8f1b3c5e927"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS so this is a no-op when the columns were already added
    # by hand (supabase/auditpulse_supabase.sql in the project root).
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_secret VARCHAR(64)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_setup_required BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("ALTER TABLE users ALTER COLUMN hashed_password DROP NOT NULL")


def downgrade() -> None:
    # Rows created without a password would violate NOT NULL again, so give
    # them an unusable placeholder before restoring the constraint.
    op.execute("UPDATE users SET hashed_password = '!' WHERE hashed_password IS NULL")
    op.alter_column("users", "hashed_password", existing_type=sa.String(255), nullable=False)
    op.drop_column("users", "auth_setup_required")
    op.drop_column("users", "mfa_enabled")
    op.drop_column("users", "mfa_secret")
