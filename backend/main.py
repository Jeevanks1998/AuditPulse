"""
main.py

FastAPI entry point for the AuditPulse backend (AI Website Audit Platform).

This wires up:
  - app lifespan (DB init on startup, connection cleanup on shutdown)
  - logging
  - CORS (so the static frontend in /assets can call this API from another
    origin during local development)
  - global exception handling -> consistent JSON error shape
  - health check endpoint
  - the API router mount point (routers themselves land in a future
    `routes/` package and get included below, e.g. auth, audits, settings)

Run locally:
    uvicorn main:app --reload

Run in Docker:
    see Dockerfile
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

# --------------------------------------------------------------------------
# Routers
# --------------------------------------------------------------------------
# api/router.py aggregates auth, audits, reports, dashboard, history,
# scheduler, and settings into one APIRouter.
from api.router import api_router

# Importing models registers every ORM class (User, Audit, Website, Issue,
# Consent, Analytics, Report, History) on Base.metadata. api/router.py's
# imports already pull most of these in transitively, but importing the
# package explicitly here means table creation in init_db() never depends
# on router import order.
import models  # noqa: F401


# --------------------------------------------------------------------------
# Lifespan
# --------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info(f"Starting {settings.APP_NAME} ({settings.APP_ENV})")
    await init_db()
    yield
    logger.info("Shutting down...")
    await close_db()


# --------------------------------------------------------------------------
# App instance
# --------------------------------------------------------------------------
app = FastAPI(
    title=settings.APP_NAME,
    description="Backend API for the AI Website Audit Platform (AuditPulse).",
    version="1.0.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)

# --------------------------------------------------------------------------
# Middleware + exception handlers (middleware/) -> auth context, request
# logging, rate limiting, CORS, and the consistent { success, error } JSON
# shape the frontend's Notifications.error(...) calls expect (see
# assets/js/api.js callers). See middleware/__init__.py for layer order.
# --------------------------------------------------------------------------
setup_middleware(app)

# --------------------------------------------------------------------------
# Static screenshot serving — banner-clip screenshots (consent/screenshots.py)
# and full-page screenshots (crawler/screenshots.py) are written to
# settings.SCREENSHOT_DIR on disk; mount that directory so the paths stored
# on Consent.banner_screenshot_path can be turned into a URL the frontend
# can load directly (see schemas.audit.ConsentOut.banner_screenshot_url).
# --------------------------------------------------------------------------
#
# Files on disk are served first; when the file isn't there (the container
# disk is wiped on every Railway redeploy, or the audit ran on a separate
# worker service) the durable copy in the database is served instead —
# see models/screenshot_blob.py and utils/screenshot_store.py.
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


# --------------------------------------------------------------------------
# Health check
# --------------------------------------------------------------------------
@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV}


@app.get("/", tags=["System"])
async def root():
    return {
        "message": f"{settings.APP_NAME} is running",
        "docs": "/docs",
        "health": "/health",
    }


# --------------------------------------------------------------------------
# Routers
# --------------------------------------------------------------------------
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
