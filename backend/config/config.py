"""
Shortcut: `from config.config import settings, logger, constants`.
"""

from config import constants
from config.database import Base, close_db, engine, get_db, init_db
from config.logging import logger, setup_logging
from config.settings import Settings, get_settings, settings

__all__ = [
    "settings",
    "get_settings",
    "Settings",
    "logger",
    "setup_logging",
    "constants",
    "Base",
    "engine",
    "get_db",
    "init_db",
    "close_db",
]
