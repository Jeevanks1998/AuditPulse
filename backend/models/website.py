"""
models/website.py

A Website is the normalized "thing being audited" — one row per
(user, hostname). Audits keep their own free-text `url` (the exact page
that was crawled, e.g. https://example.com/pricing) but link back to a
Website so the dashboard/history can group and trend multiple audits of
the same site over time, and so scheduler.py can attach a recurring job
to a tracked site rather than a raw string.

`get_or_create_website` is the single place that resolves a URL to a
Website row; api/audit.py and api/scheduler.py both call it when an
audit is created so the mapping only lives in one place.
"""

from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING
from urllib.parse import urlparse

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import Base

if TYPE_CHECKING:
    from models.user import User
    from models.audit import Audit


class Website(Base):
    __tablename__ = "websites"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    url: Mapped[str] = mapped_column(String(500))
    hostname: Mapped[str] = mapped_column(String(255), index=True)
    favicon_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    is_monitored: Mapped[bool] = mapped_column(Boolean, default=False)
    audit_count: Mapped[int] = mapped_column(Integer, default=0)
    last_overall_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    first_audited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_audited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # ----------------------------------------------------------------
    # Relationships
    # ----------------------------------------------------------------
    user: Mapped["User"] = relationship("User", back_populates="websites")
    audits: Mapped[List["Audit"]] = relationship(
        "Audit", back_populates="website", order_by="Audit.created_at.desc()"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Website id={self.id} hostname={self.hostname!r}>"


def hostname_of(url: str) -> str:
    """Best-effort hostname extraction, mirrors Utils.hostnameOf on the frontend."""
    parsed = urlparse(url if "//" in url else f"//{url}")
    return (parsed.hostname or url).lower()


async def get_or_create_website(db: AsyncSession, user_id: int, url: str) -> Website:
    """
    Resolve (user_id, hostname) to a Website row, creating one if this is
    the first time this user has audited this hostname.
    """
    host = hostname_of(url)
    result = await db.execute(
        select(Website).where(Website.user_id == user_id, Website.hostname == host)
    )
    website = result.scalar_one_or_none()
    if website is None:
        website = Website(user_id=user_id, url=url, hostname=host)
        db.add(website)
        await db.flush()  # assign an id without committing the caller's transaction
    return website


async def record_audit_result(website: Website, overall_score: Optional[int], when: datetime) -> None:
    """Bump a Website's rollup fields after one of its audits completes."""
    website.audit_count += 1
    website.last_audited_at = when
    if website.first_audited_at is None:
        website.first_audited_at = when
    if overall_score is not None:
        website.last_overall_score = overall_score
