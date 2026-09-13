"""
reports/evidence.py

Builds the complete evidence ZIP (§5.2): the PDF report plus every
screenshot, cookie, and network-evidence JSON file captured for an audit,
bundled as one downloadable archive (api/reports.py's
`/{audit_id}/evidence.zip`, and the "evidence_zip" attachment key in
emailer/attachments.py's "Send to POC" modal). Everything here is read
straight off a single already-built ReportPayload (§8) — this module
doesn't re-derive or re-fetch anything, it only packages what
reports/generator.py already computed.
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO

from reports.generator import ReportPayload
from utils.screenshots import screenshot_url_to_path


def evidence_zip_filename(audit_id: int) -> str:
    return f"audit-{audit_id}-evidence.zip"


def build_evidence_zip(payload: ReportPayload, *, pdf_bytes: bytes = None) -> bytes:
    """Returns the evidence ZIP's raw bytes. `pdf_bytes` is optional — the
    ZIP is still built (minus the PDF entry) if the caller doesn't have one
    cached/generated yet, same degrade-gracefully contract as the rest of
    the export pipeline."""
    buffer = BytesIO()

    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if pdf_bytes:
            zf.writestr(f"audit-{payload.audit_id}-report.pdf", pdf_bytes)

        for shot in payload.screenshots:
            disk_path = screenshot_url_to_path(shot.get("url"))
            if not disk_path:
                continue
            try:
                with open(disk_path, "rb") as fh:
                    content = fh.read()
            except OSError:
                continue
            zf.writestr(f"screenshots/{shot.get('key', 'screenshot')}.png", content)

        if payload.cookie_evidence:
            zf.writestr("cookie-evidence.json", json.dumps(payload.cookie_evidence, indent=2, default=str))

        if payload.network_evidence:
            zf.writestr("network-evidence.json", json.dumps(payload.network_evidence, indent=2, default=str))

        if payload.analytics is not None:
            zf.writestr("analytics-runtime.json", json.dumps(payload.analytics, indent=2, default=str))

        if payload.consent is not None:
            zf.writestr("consent-evidence.json", json.dumps(payload.consent, indent=2, default=str))

        zf.writestr(
            "findings.json",
            json.dumps(
                {
                    "audit_id": payload.audit_id,
                    "url": payload.url,
                    "overall": payload.overall,
                    "generated_at": payload.generated_at,
                    "severity_counts": payload.severity_counts,
                    "findings": payload.findings,
                },
                indent=2,
                default=str,
            ),
        )

    return buffer.getvalue()


__all__ = ["build_evidence_zip", "evidence_zip_filename"]
