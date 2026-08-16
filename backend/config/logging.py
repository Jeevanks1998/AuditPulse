"""
config/logging.py

Configures application-wide logging. Uses loguru for nicer formatting while
still routing standard-library `logging` records (from uvicorn, sqlalchemy,
etc.) through the same sinks, so every log line looks consistent regardless
of where it came from.
"""

import logging
import sys
from pathlib import Path

from loguru import logger

from config.settings import settings


class InterceptHandler(logging.Handler):
    """Redirects stdlib `logging` records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging() -> None:
    """Call once at application startup (see main.py)."""
    logger.remove()

    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> "
            "- <level>{message}</level>"
        ),
        backtrace=settings.DEBUG,
        diagnose=settings.DEBUG,
    )

    if settings.LOG_TO_FILE:
        log_path = Path(settings.LOG_FILE_PATH)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_path,
            level=settings.LOG_LEVEL,
            rotation="10 MB",
            retention="14 days",
            compression="zip",
            enqueue=True,
            backtrace=settings.DEBUG,
            diagnose=False,
        )

    # Route uvicorn / fastapi / sqlalchemy stdlib loggers through loguru
    for name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "fastapi",
        "sqlalchemy.engine",
    ):
        logging.getLogger(name).handlers = [InterceptHandler()]
        logging.getLogger(name).propagate = False

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    logger.info(f"Logging configured (level={settings.LOG_LEVEL})")


__all__ = ["logger", "setup_logging"]
