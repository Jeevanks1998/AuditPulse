"""
One row per finding, so findings can be queried and tracked.
sync_issues_from_findings() keeps them in line with Audit.findings.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from config.database import Base

if TYPE_CHECKING:
    from models.audit import Audit


class IssueStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class IssueSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)

    module: Mapped[str] = mapped_column(String(40), index=True)  # ai|pdf|consent|analytics|journey
    severity: Mapped[str] = mapped_column(String(20), default=IssueSeverity.WARNING.value, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    recommendation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    element_selector: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default=IssueStatus.OPEN.value, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    audit: Mapped["Audit"] = relationship("Audit", back_populates="issues")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Issue id={self.id} module={self.module!r} severity={self.severity!r}>"


def _clip(text, limit: int):
    if text is None:
        return None
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def sync_issues_from_findings(db: AsyncSession, audit: "Audit", findings: List[dict]) -> None:
    """Replaces an audit's Issue rows with its current findings."""
    # Don't use audit.issues here (lazy loading fails in async code); query instead.
    existing_issues = (
        await db.execute(select(Issue).where(Issue.audit_id == audit.id))
    ).scalars().all()
    for existing in existing_issues:
        await db.delete(existing)
    await db.flush()

    for f in findings:
        db.add(
            Issue(
                audit_id=audit.id,
                module=(f.get("module") or "general")[:40],
                severity=(f.get("severity") or IssueSeverity.WARNING.value)[:20],
                # Long link names (e.g. "Download, 2024 Climate and Biodiversity Report, ...") overflowed the column.
                title=_clip(f.get("title") or "", 200),
                description=f.get("description", ""),
                recommendation=f.get("recommendation"),
                element_selector=_clip(f.get("element_selector"), 300),
            )
        )
