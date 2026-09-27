"""
database/

Home for everything DB-shaped that isn't "how is the engine configured"
(that's config/database.py — see its docstring). This package covers the
three concerns that build on top of it:

  session.py    - `session_scope()`, a commit/rollback-managed async
                   context manager for DB access outside a request
                   (workers/, scheduler/, seed.py), plus re-exports of
                   Base/engine/get_db/init_db/close_db so callers have
                   one import path.
  migrations/   - Alembic environment (`alembic.ini` at the backend
                   root points `script_location` here). Run migrations
                   with:
                       alembic upgrade head
                       alembic revision --autogenerate -m "message"
  seed.py       - Idempotent dev-data seed script:
                       python -m database.seed

Mirrors config/config.py's role for config/: a thin aggregator so other
modules can do

    from database import session_scope, get_db

instead of reaching into database.session directly.
"""

from database.session import (
    AsyncSessionLocal,
    Base,
    close_db,
    engine,
    get_db,
    init_db,
    session_scope,
)

__all__ = [
    "Base",
    "engine",
    "AsyncSessionLocal",
    "get_db",
    "init_db",
    "close_db",
    "session_scope",
]
