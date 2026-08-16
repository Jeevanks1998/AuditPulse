"""
emailer/attachments.py

Resolves the attachment keys the "Send to POC" modal's checkboxes send
(§9.2's "Suggested attachment options") into real (filename, mimetype,
bytes) tuples — never fabricated placeholders, per §14. Every attachment
is built from the same ReportPayload (§8) the PDF/JSON/evidence-ZIP
exports already use; this module just picks which pieces of it to
package for one email.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional

from reports.evidence import build_evidence_zip, evidence_zip_filename
from reports.generator import ReportPayload
from utils.screenshots import screenshot_url_to_path


@dataclass
class ResolvedAttachment:
    filename: str
    mimetype: str
    content: bytes


# Human-readable labels for the frontend's checkbox list (§9.2).
ATTACHMENT_CHOICES: Dict[str, str] = {
    "pdf": "Audit Report PDF",
    "consent_screenshots": "Consent screenshots",
    "analytics_runtime": "Analytics runtime evidence",
    "cookie_evidence": "Cookie evidence",
    "network_evidence": "Network evidence",
    "evidence_zip": "Complete ZIP evidence package",
}


def resolve_attachments(
    keys: List[str],
    payload: ReportPayload,
    *,
    audit_id: int,
    pdf_bytes: Optional[bytes] = None,
) -> List[ResolvedAttachment]:
    """
    Returns only the attachments that were both requested *and* actually
    have data for this audit (e.g. "consent_screenshots" is silently
    skipped, not sent empty, when the consent module didn't run) — the
    caller (emailer.service) records which keys were actually attached.
    """
    resolved: List[ResolvedAttachment] = []
    seen = set(keys)

    if "pdf" in seen and pdf_bytes:
        resolved.append(ResolvedAttachment(f"audit-{audit_id}-report.pdf", "application/pdf", pdf_bytes))

    if "consent_screenshots" in seen:
        for shot in payload.screenshots:
            disk_path = screenshot_url_to_path(shot.get("url"))
            if not disk_path:
                continue
            try:
                with open(disk_path, "rb") as fh:
                    content = fh.read()
            except OSError:
                continue
            resolved.append(ResolvedAttachment(f"{shot.get('key', 'screenshot')}.png", "image/png", content))

    if "analytics_runtime" in seen and payload.analytics is not None:
        resolved.append(
            ResolvedAttachment(
                "analytics-runtime.json",
                "application/json",
                json.dumps(payload.analytics, indent=2, default=str).encode("utf-8"),
            )
        )

    if "cookie_evidence" in seen and payload.cookie_evidence:
        resolved.append(
            ResolvedAttachment(
                "cookie-evidence.json",
                "application/json",
                json.dumps(payload.cookie_evidence, indent=2, default=str).encode("utf-8"),
            )
        )

    if "network_evidence" in seen and payload.network_evidence:
        resolved.append(
            ResolvedAttachment(
                "network-evidence.json",
                "application/json",
                json.dumps(payload.network_evidence, indent=2, default=str).encode("utf-8"),
            )
        )

    if "evidence_zip" in seen:
        zip_bytes = build_evidence_zip(payload, pdf_bytes=pdf_bytes)
        resolved.append(ResolvedAttachment(evidence_zip_filename(audit_id), "application/zip", zip_bytes))

    return resolved
