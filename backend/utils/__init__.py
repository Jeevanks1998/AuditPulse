"""
utils/

Small, dependency-light helpers reused across services/api/crawler
modules, split by concern rather than dumped in one file:

  logger.py      - get_logger / log_duration / log_context, layered on
                   config/logging.py's already-configured logger.
  helpers.py     - generic bits with no other home: time, retries,
                   bounded concurrency, dict/list wrangling, tokens.
  validators.py  - standalone bool/reason checks for code paths outside
                   a Pydantic request body (services, jobs, scripts).
  formatter.py   - human-readable score/byte/duration/relative-time
                   strings, mirroring assets/js/utils.js's formatting.
  urls.py        - URL normalization/parsing for the crawler and
                   SEO/links checks.
  screenshots.py - filesystem lifecycle for captured screenshots
                   (crawler/screenshots.py owns the actual capture).
  file_manager.py- generic, path-traversal-safe file I/O for new
                   features that need disk storage.

This top-level module re-exports the handful of names reached for most
often, mirroring config/config.py's role for config/:

    from utils import get_logger, normalize_url, score_band

Less-common helpers stay accessed via their own submodule
(`utils.validators.is_valid_email`, `utils.file_manager.FileManager`,
etc.) rather than being flattened here too.
"""

from utils.formatter import format_bytes, format_duration, format_relative_time, score_band
from utils.helpers import chunked, generate_token, retry_async, safe_get, utc_now
from utils.logger import get_logger, log_context, log_duration
from utils.urls import hostname_of, is_valid_url, normalize_url
from utils.validators import is_valid_email, validate_pagination

__all__ = [
    "get_logger",
    "log_duration",
    "log_context",
    "utc_now",
    "generate_token",
    "chunked",
    "safe_get",
    "retry_async",
    "is_valid_email",
    "validate_pagination",
    "score_band",
    "format_bytes",
    "format_duration",
    "format_relative_time",
    "hostname_of",
    "is_valid_url",
    "normalize_url",
]
