"""
config/config.py

Convenience aggregator so the rest of the app can do:

    from config.config import settings, logger, constants

instead of importing from several config submodules individually.
Kept thin on purpose — actual logic lives in settings.py / database.py /
logging.py / constants.py.
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
