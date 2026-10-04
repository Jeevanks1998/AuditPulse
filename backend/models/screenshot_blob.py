"""
models/screenshot_blob.py

Durable copy of every evidence screenshot (consent banner / preferences /
reject / accept, Journey Map pages and interactions).

Screenshots are written to settings.SCREENSHOT_DIR on local disk while an
audit runs. On Railway that disk is wiped on every redeploy/restart, and a
separate worker service has its own disk — so the files behind the stored
"/screenshots/..." URLs disappeared and the report showed "Screenshot not
available". After each audit the new files are copied here (re-encoded as
compact JPEG) and main.py's /screenshots route falls back to this table.

key = path relative to SCREENSHOT_DIR with "/" separators — exactly the
part after "/screenshots/" in the URL the report uses.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class ScreenshotBlob(Base):
    __tablename__ = "screenshot_blobs"

    key: Mapped[str] = mapped_column(String(512), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    content_type: Mapped[str] = mapped_column(String(40), default="image/jpeg")
    size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
