# ==============================================================================
# AuditPulse backend — Dockerfile
# ==============================================================================
FROM python:3.11-slim-bookworm AS base

# Prevents Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Celery's `-A` app-loading only adds the cwd to sys.path while it resolves
# the app object itself, then removes it again — so any top-of-file import
# (workers.celery_worker, scheduler.jobs, etc.) works fine at startup, but
# the deferred/lazy imports inside every task body (models, services,
# reports, pdf, crawler, ...) fail with ModuleNotFoundError once a task
# actually runs, because cwd is already gone from sys.path by then.
# uvicorn doesn't hit this — it inserts cwd itself when resolving
# "main:app" and keeps it there. Pinning PYTHONPATH here makes /app
# permanently importable for both processes, regardless of Celery's
# start-up-only sys.path dance.
ENV PYTHONPATH=/app

# System dependencies needed to build asyncpg / cryptography wheels
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright's own OS-level dependencies (fonts, libnss3, etc.) for headless
# Chromium — needed for crawler/screenshots.py and consent/screenshots.py.
RUN playwright install --with-deps chromium

# Copy application source
COPY . .

# Screenshots are written to settings.SCREENSHOT_DIR ("screenshots" by
# default, relative to WORKDIR) — create it and hand it to appuser before
# dropping root, since the app process can't chown it itself.
RUN mkdir -p /app/screenshots && useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
