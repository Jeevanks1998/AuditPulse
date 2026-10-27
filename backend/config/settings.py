"""
All settings, loaded from environment variables / .env. Read config from `settings`, not os.getenv().
"""

from functools import lru_cache
from typing import List, Optional

from pydantic import field_validator
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

    # --- Access Portal integration ---
    # Shared key the portal sends as `Authorization: Bearer <key>`.
    # Empty = integration off (every call refused).
    ACCESS_PORTAL_API_KEY: str = ""

    # --- Database ---
    DATABASE_URL: str = "postgresql+asyncpg://auditpulse:auditpulse@localhost:5432/auditpulse"
    DB_ECHO: bool = False
    # Small on purpose: several processes each have their own pool, and
    # Supabase limits total connections.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5

    # --- Redis / Celery ---
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # --- CORS ---
    # Comma-separated; use the CORS_ORIGINS property for the list.
    CORS_ORIGINS_RAW: str = "http://localhost:3000"

    # --- Third-party APIs ---
    # "anthropic" (ANTHROPIC_API_KEY) or "groq" (GROQ_API_KEY, free tier).
    AI_PROVIDER: str = "anthropic"
    ANTHROPIC_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    # Optional model override; empty = the provider's default in ai/provider.py.
    AI_MODEL: str = ""
    GOOGLE_PAGESPEED_API_KEY: str = ""

    # --- Crawler (crawler/) ---
    CRAWLER_USER_AGENT: str = "AuditPulseBot/1.0 (+https://auditpulse.example.com/bot)"
    CRAWLER_CONCURRENCY: int = 5
    CRAWLER_REQUEST_TIMEOUT_SECONDS: float = 15.0
    CRAWLER_ENABLE_SCREENSHOTS: bool = True
    SCREENSHOT_DIR: str = "screenshots"
    # Keep screenshots in the database too: the server disk is wiped on every redeploy.
    SCREENSHOT_DB_ENABLED: bool = True
    SCREENSHOT_DB_RETENTION_DAYS: int = 30
    SCREENSHOT_DB_MAX_WIDTH: int = 1280
    SCREENSHOT_DB_MAX_HEIGHT: int = 8000
    SCREENSHOT_DB_JPEG_QUALITY: int = 68
    # Turns the live browser checks (consent and analytics) on or off. Static checks always run.
    CRAWLER_ENABLE_RUNTIME_CHECKS: bool = True
    # Force a consent region ("IN", "EU", "UK", "US-CA"). Unset = detect from the site.
    CONSENT_TARGET_REGION: Optional[str] = None
    # SSRF protection: audits only reach public addresses. Enable only for local tests on 127.0.0.1.
    ALLOW_PRIVATE_NETWORK_TARGETS: bool = False

    # API docs (/docs, /redoc). Local development only.
    ENABLE_API_DOCS: bool = False

    # --- Journey Map (journey/) ---
    # Interaction tests per audit / per page.
    JOURNEY_MAX_TESTED_INTERACTIONS: int = 40
    JOURNEY_MAX_TESTS_PER_PAGE: int = 8
    # Time limits (seconds): page discovery, interaction tests, and the whole module.
    JOURNEY_SCAN_BUDGET_S: int = 300
    JOURNEY_TEST_BUDGET_S: int = 600
    JOURNEY_HARD_TIMEOUT_S: int = 1000
    MODULE_HARD_TIMEOUT_S: int = 300   # consent / analytics step safety net
    JOURNEY_ENABLE_INTERACTION_TESTS: bool = True

    # --- Reports ---
    # Where report exports are cached on disk.
    REPORTS_DIR: str = "reports_output"

    # --- Email (emailer/) ---
    # Credentials only from the environment. Empty SMTP_HOST = email off.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_FROM_EMAIL: str = "reports@auditpulse.example.com"
    SMTP_FROM_NAME: str = "AuditPulse"
    # Frontend address for links in emails. Empty = first https origin in CORS_ORIGINS_RAW.
    FRONTEND_URL: str = ""

    # --- Logging ---
    LOG_LEVEL: str = "INFO"
    LOG_TO_FILE: bool = True
    LOG_FILE_PATH: str = "logs/app.log"

    # --- CORS (middleware/cors.py) ---
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_MAX_AGE_SECONDS: int = 600

    # --- Rate limiting ---
    # Uses Redis so limits are shared between processes; falls back to memory if Redis is down.
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_AUTH_REQUESTS: int = 10  # stricter limit for /auth/*
    RATE_LIMIT_AUTH_WINDOW_SECONDS: int = 60
    RATE_LIMIT_EXEMPT_PATHS_RAW: str = "/health,/docs,/redoc,/openapi.json"

    @field_validator("DATABASE_URL")
    @classmethod
    def _validate_database_url(cls, v: str) -> str:
        """Gives a clear error when DATABASE_URL is set but empty."""
        v = v.strip()
        if v:
            # Supabase gives postgres:// URLs; switch to the async driver automatically.
            if v.startswith("postgres://"):
                v = "postgresql+asyncpg://" + v[len("postgres://"):]
            elif v.startswith("postgresql://"):
                v = "postgresql+asyncpg://" + v[len("postgresql://"):]
            # asyncpg takes `ssl=`, not libpq's `sslmode=`.
            if v.startswith("postgresql+asyncpg://") and "sslmode=" in v:
                v = v.replace("sslmode=", "ssl=")
            return v
        if not v:
            raise ValueError(
                "DATABASE_URL is set but empty. In Railway: Service -> "
                "Variables -> DATABASE_URL must contain a real Postgres "
                "connection string (this project uses an external "
                "Supabase database, not a Railway Postgres plugin), e.g. "
                "postgresql+asyncpg://postgres.xxxx:PASSWORD@aws-0-"
                "<region>.pooler.supabase.com:6543/postgres. If it's "
                "meant to reference a Railway service variable, confirm "
                "that service actually exists in this project."
            )
        return v

    @property
    def CORS_ORIGINS(self) -> List[str]:
        """Allowed CORS origins as a list."""
        return [o.strip() for o in self.CORS_ORIGINS_RAW.split(",") if o.strip()]

    @property
    def RATE_LIMIT_EXEMPT_PATHS(self) -> List[str]:
        """Path prefixes the rate limiter skips."""
        return [p.strip() for p in self.RATE_LIMIT_EXEMPT_PATHS_RAW.split(",") if p.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() == "production"

    @property
    def EMAIL_ENABLED(self) -> bool:
        """False until SMTP_HOST is set."""
        return bool(self.SMTP_HOST.strip())

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Settings are read once per process."""
    return Settings()


settings = get_settings()
