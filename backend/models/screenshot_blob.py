"""
Database copy of every evidence screenshot. The server disk is wiped on
redeploy, so after each audit the files are copied here (as JPEG) and
/screenshots falls back to this table. key = the path after "/screenshots/".
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
