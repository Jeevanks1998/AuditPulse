"""
config/settings.py

Central, typed application settings loaded from environment variables / .env.
Every other module should read configuration from `settings` (the singleton
below) rather than calling os.getenv() directly, so we have one source of
truth and get validation for free from Pydantic.
"""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- App ---
    APP_NAME: str = "AuditPulse API"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # --- Security / JWT ---
    SECRET_KEY: str = "change-this-to-a-long-random-string-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- Database ---
    DATABASE_URL: str = "postgresql+asyncpg://auditpulse:auditpulse@localhost:5432/auditpulse"
    DB_ECHO: bool = False
    # Kept small deliberately: at least two processes (the combined
    # web+worker+beat service in railway.json and the standalone worker
    # in railway-worker.json) each create their own engine/pool, and in
    # production DATABASE_URL points at Supabase's pooler, which caps
    # total concurrent clients (session-mode pooler: 15 by default on
    # smaller Supabase tiers). pool_size=10/max_overflow=20 (the old
    # defaults) let a *single* process alone request up to 30 connections
    # — well past that cap before a second process even starts. See
    # config/database.py's engine construction for the accompanying
    # PgBouncer/transaction-pooler settings.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5

    # --- Redis / Celery ---
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # --- CORS ---
    # Stored as a raw comma-separated string (see .env) so pydantic-settings
    # doesn't try to JSON-decode it as a list; use the `CORS_ORIGINS`
    # property below to get the parsed List[str].
    CORS_ORIGINS_RAW: str = "http://localhost:3000"

    # --- Third-party APIs ---
    AI_PROVIDER: str = "anthropic"
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_PAGESPEED_API_KEY: str = ""

    # --- Crawler (crawler/) ---
    CRAWLER_USER_AGENT: str = "AuditPulseBot/1.0 (+https://auditpulse.example.com/bot)"
    CRAWLER_CONCURRENCY: int = 5
    CRAWLER_REQUEST_TIMEOUT_SECONDS: float = 15.0
    CRAWLER_ENABLE_SCREENSHOTS: bool = True
    SCREENSHOT_DIR: str = "screenshots"
    # Gates the Playwright-based click-through/runtime validation passes in
    # consent.runtime and analytics.runtime (separate from the plain
    # screenshot capture above) — off this, both modules still run their
    # full static/markup checks, just without live browser verification.
    CRAWLER_ENABLE_RUNTIME_CHECKS: bool = True

    # --- Reports (reports/report_storage.py) ---
    # Where generated report exports (HTML/JSON) are cached on disk, keyed
    # by audit id, so repeat downloads of the same report don't re-run the
    # AI pipeline in reports/generator.py.
    REPORTS_DIR: str = "reports_output"

    # --- Email / POC report delivery (emailer/) ---
    # Credentials come from the environment only (.env), never source
    # code, per requirements §9.4/§14. SMTP_HOST empty means the email
    # feature is unconfigured — emailer.service checks this and returns a
    # clear failure rather than silently pretending to send.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_FROM_EMAIL: str = "reports@auditpulse.example.com"
    SMTP_FROM_NAME: str = "AuditPulse"

    # --- Logging ---
    LOG_LEVEL: str = "INFO"
    LOG_TO_FILE: bool = True
    LOG_FILE_PATH: str = "logs/app.log"

    # --- CORS (middleware/cors.py) ---
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_MAX_AGE_SECONDS: int = 600

    # --- Rate limiting (middleware/rate_limit.py) ---
    # Backed by Redis (same REDIS_URL as Celery) so limits are shared across
    # every uvicorn worker process; falls back to an in-memory counter if
    # Redis is unreachable, so a Redis outage degrades to per-process
    # limiting instead of taking the API down.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_AUTH_REQUESTS: int = 10  # tighter window for /auth/* (brute-force protection)
    RATE_LIMIT_AUTH_WINDOW_SECONDS: int = 60
    RATE_LIMIT_EXEMPT_PATHS_RAW: str = "/health,/docs,/redoc,/openapi.json"

    @property
    def CORS_ORIGINS(self) -> List[str]:
        """Parsed list of allowed CORS origins from CORS_ORIGINS_RAW."""
        return [o.strip() for o in self.CORS_ORIGINS_RAW.split(",") if o.strip()]

    @property
    def RATE_LIMIT_EXEMPT_PATHS(self) -> List[str]:
        """Parsed list of path prefixes middleware/rate_limit.py never throttles."""
        return [p.strip() for p in self.RATE_LIMIT_EXEMPT_PATHS_RAW.split(",") if p.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    @property
    def EMAIL_ENABLED(self) -> bool:
        """False until SMTP_HOST is configured in the environment — see emailer/service.py."""
        return bool(self.SMTP_HOST.strip())

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — env is only parsed once per process."""
    return Settings()


settings = get_settings()
