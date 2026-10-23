#!/bin/sh
# Render start command (render.yaml -> dockerCommand: sh render-start.sh).
# Applies database migrations, then starts the API. Audits run inside the
# API process (FastAPI BackgroundTasks), so no separate worker is needed.
alembic upgrade head || echo "alembic upgrade failed, continuing"
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
