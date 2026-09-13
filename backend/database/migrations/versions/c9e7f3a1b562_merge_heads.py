"""merge heads

Revision ID: c9e7f3a1b562
Revises: a1c8e5f42d17, b7d4e1f9a203
Create Date: 2026-09-13 00:00:00.000000

The migration history diverged into two independent chains that never
joined back up:

  e4312ce42c87 -> f1a9c6d2b834 -> a1c8e5f42d17  (users.role /
                                                  users.auditpulse_access)
  682b36c9a001 -> 9c3f2a7b5e14 -> b7d4e1f9a203  (consent_results.*_checks)

Both chains have down_revision=None, i.e. two separate roots that were
never merged, leaving Alembic with two heads
(a1c8e5f42d17, b7d4e1f9a203). `alembic upgrade head` refuses to run
against multiple heads ("Multiple head revisions are present for given
argument 'head'"), which is exactly what backend/railway.json's
startCommand runs before uvicorn starts (`alembic upgrade head && ...`)
— so every deploy fails at the migration step and the API container
never comes up. This is a no-op merge (no schema changes of its own)
that just gives Alembic a single head again so deploys succeed.
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