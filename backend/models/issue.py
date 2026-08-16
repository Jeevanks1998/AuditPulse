"""
models/issue.py

Issue normalizes Audit.findings (a denormalized JSON list, kept for fast
report reads) into real rows so findings can be queried, filtered, and
tracked across their lifecycle independently of the audit that produced
them — e.g. "show me every open critical accessibility issue across all
my sites" or "mark this finding as resolved / ignored".

`sync_issues_from_findings` is the one place that keeps the two
representations (Audit.findings JSON <-> Issue rows) in agreement; it's
called by the audit pipeline right after findings are generated.
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

    module: Mapped[str] = mapped_column(String(40), index=True)  # ai|pdf|consent|analytics|performance|accessibility|seo
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

    # ----------------------------------------------------------------
    # Relationships
    # ----------------------------------------------------------------
    audit: Mapped["Audit"] = relationship("Audit", back_populates="issues")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Issue id={self.id} module={self.module!r} severity={self.severity!r}>"


async def sync_issues_from_findings(db: AsyncSession, audit: "Audit", findings: List[dict]) -> None:
    """
    Replace an audit's Issue rows with the current `findings` JSON list.
    Called once, right after the pipeline finalizes an audit's findings,
    so the normalized table always matches what report.py / history
    surface from Audit.findings.
    """
    # NOTE: don't touch `audit.issues` here (lazy-loaded relationship) — in
    # an async engine that triggers implicit IO outside of a greenlet and
    # raises `sqlalchemy.exc.MissingGreenlet`. Query explicitly instead.
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
                module=f.get("module", "general"),
                severity=f.get("severity", IssueSeverity.WARNING.value),
                title=f.get("title", ""),
                description=f.get("description", ""),
                recommendation=f.get("recommendation"),
                element_selector=f.get("element_selector"),
            )
        )
