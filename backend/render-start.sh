#!/bin/sh
# Render start: run migrations, then start the API (audits run inside the API process).
alembic upgrade head || echo "alembic upgrade failed, continuing"
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
