"""
reports/evidence.py

Builds the complete evidence ZIP package (requirements §5.2):

    AuditPulse-Evidence/
    ├── audit-report.pdf
    ├── screenshots/
    │   ├── consent-initial.png
    │   ├── consent-preferences.png
    │   ├── consent-reject.png
    │   └── consent-accept.png
    ├── analytics/
    │   ├── analytics-runtime.json
    │   └── network-evidence.json
    └── consent/
        ├── cookies-before-consent.json
        ├── cookies-after-reject.json
        └── cookies-after-accept.json

Every file in the archive is built from the same `ReportPayload` the
PDF/HTML/JSON exports and the POC email attachments all read (§8's
"single canonical report payload") — nothing here re-derives detection
or scoring, it only packages what's already on the payload. Screenshot
files are pulled straight off disk via utils.screenshots.screenshot_url_to_path
so the ZIP contains the real captured PNGs, not just their URLs.
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Optional

from reports.generator import ReportPayload
from utils.screenshots import screenshot_url_to_path

_ROOT = "AuditPulse-Evidence"


def build_evidence_zip(payload: ReportPayload, pdf_bytes: Optional[bytes] = None) -> bytes:
    """Returns the complete evidence package as ZIP bytes."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        if pdf_bytes:
            zf.writestr(f"{_ROOT}/audit-report.pdf", pdf_bytes)

        for shot in payload.screenshots:
            disk_path = screenshot_url_to_path(shot.get("url"))
            if not disk_path:
                continue
            extension = Path(disk_path).suffix or ".png"
            key = shot.get("key", "screenshot")
            zf.write(disk_path, f"{_ROOT}/screenshots/{key}{extension}")

        if payload.analytics is not None:
            zf.writestr(
                f"{_ROOT}/analytics/analytics-runtime.json",
                json.dumps(payload.analytics, indent=2, default=str),
            )
        if payload.network_evidence:
            zf.writestr(
                f"{_ROOT}/analytics/network-evidence.json",
                json.dumps(payload.network_evidence, indent=2, default=str),
            )

        cookie_files = {
            "before_consent": "cookies-before-consent.json",
            "after_reject": "cookies-after-reject.json",
            "after_accept": "cookies-after-accept.json",
        }
        for phase, filename in cookie_files.items():
            cookies = payload.cookie_evidence.get(phase)
            if cookies is None:
                continue
            zf.writestr(f"{_ROOT}/consent/{filename}", json.dumps(cookies, indent=2, default=str))

        if payload.consent is not None:
            zf.writestr(
                f"{_ROOT}/consent/consent-summary.json",
                json.dumps(payload.consent, indent=2, default=str),
            )

    return buffer.getvalue()


def evidence_zip_filename(audit_id: int) -> str:
    return f"audit-{audit_id}-evidence.zip"
