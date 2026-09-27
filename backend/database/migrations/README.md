# database/migrations

Alembic migration environment for the backend's async SQLAlchemy models
(`models/`). `env.py` reads the connection string from
`config.settings.settings.DATABASE_URL`, so `.env` is the one place that
needs updating between environments — nothing here needs editing per-env.

Run all commands from `backend/` (where `alembic.ini` lives).

## Common commands

Generate a migration from model changes:

```bash
alembic revision --autogenerate -m "add website favicon column"
```

Always review the generated file in `versions/` before applying it —
autogenerate is a good first draft, not a guarantee (it won't detect
every change, e.g. some column renames look like a drop + add).

Apply pending migrations:

```bash
alembic upgrade head
```

Roll back one migration:

```bash
alembic downgrade -1
```

Show current DB revision / full history:

```bash
alembic current
alembic history --verbose
```

## Notes

- `main.py`'s `init_db()` (`config/database.py`) calls
  `Base.metadata.create_all` on startup for local/dev convenience. That's
  fine for a throwaway local DB, but once a schema has real data in it,
  use these migrations instead — `create_all` never alters or drops
  existing columns, so it silently diverges from `models/` over time.
- `database/seed.py` assumes the schema is already up to date; run
  `alembic upgrade head` before seeding a fresh database.
