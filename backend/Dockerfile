# AuditPulse backend image
FROM python:3.11-slim-bookworm AS base

# No .pyc files, unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Keep /app importable for Celery tasks too (Celery drops the working
# directory from the import path after startup).
ENV PYTHONPATH=/app

# Install Chromium to a fixed path so the non-root app user can find it.
# Without this, every browser check fails at runtime.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Build tools for asyncpg / cryptography
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Python packages first, for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium and its system libraries for the browser checks
RUN playwright install --with-deps chromium

# App source
COPY . .

# Screenshot folder and Chromium cache must belong to the app user.
RUN mkdir -p /app/screenshots && useradd -m appuser \
    && chown -R appuser:appuser /app /ms-playwright
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
