"""
AuditPulse API entry point: start-up/shut-down, logging, middleware, error
handling, screenshots, health check and the API routes.

Run locally: uvicorn main:app --reload
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config.config import (
    close_db,
    init_db,
    logger,
    setup_logging,
    settings,
)
from middleware import setup_middleware

# Routers
from api.router import api_router

# Import every model so init_db() creates all tables, whatever the import order.
import models  # noqa: F401


_DEFAULT_SECRET = "change-this-to-a-long-random-string-in-production"


def _check_secrets() -> None:
    """Refuse to start with the sample secret outside development (anyone could forge sessions)."""
    weak = settings.SECRET_KEY == _DEFAULT_SECRET or len(settings.SECRET_KEY) < 32
    local_db = any(h in settings.DATABASE_URL for h in ("@localhost", "@127.0.0.1", "@db:", "@postgres:"))
    if weak and not local_db:
        raise RuntimeError(
            "SECRET_KEY is missing or too weak. Set SECRET_KEY to a random value of at least 32 characters "
            "(e.g. `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`) in the environment.")
    if weak:
        logger.warning("SECRET_KEY is the development default — never use this in production.")


# Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    _check_secrets()
    logger.info(f"Starting {settings.APP_NAME} ({settings.APP_ENV})")
    await init_db()
    yield
    logger.info("Shutting down...")
    await close_db()


# App
app = FastAPI(
    title=settings.APP_NAME,
    description="Backend API for the AI Website Audit Platform (AuditPulse).",
    version="1.0.0",
    # API docs only when ENABLE_API_DOCS is on.
    docs_url="/docs" if settings.ENABLE_API_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_API_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_API_DOCS else None,
    lifespan=lifespan,
)

# Middleware and error handlers (see middleware/__init__.py for the order).
setup_middleware(app)

# Screenshots: served from disk, or from the database copy when the file is
# gone (the server disk is wiped on redeploy). See utils/screenshot_store.py.
_screenshot_dir = Path(settings.SCREENSHOT_DIR)
_screenshot_dir.mkdir(parents=True, exist_ok=True)


@app.get("/screenshots/{key:path}", include_in_schema=False)
async def serve_screenshot(key: str):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse, Response

    from utils.screenshot_store import load_screenshot, safe_key

    clean = safe_key(key)
    if not clean:
        raise HTTPException(status_code=404, detail="Not found")
    root = _screenshot_dir.resolve()
    path = (root / clean).resolve()
    cache = {"Cache-Control": "public, max-age=604800, immutable"}
    if root in path.parents and path.is_file():
        return FileResponse(str(path), headers=cache)
    stored = await load_screenshot(clean)
    if stored is None:
        raise HTTPException(status_code=404, detail="Screenshot not found")
    content, content_type = stored
    return Response(content=content, media_type=content_type, headers=cache)


# Health check
@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok"}


@app.get("/", tags=["System"])
async def root():
    return {"message": f"{settings.APP_NAME} is running", "health": "/health"}


# Routes
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
