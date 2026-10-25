"""
Builds the evidence ZIP: the PDF plus every screenshot and cookie/network JSON, all from one ReportPayload.
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
    """Returns the ZIP bytes. Without `pdf_bytes` the ZIP is built without the PDF."""
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

        # Consent evidence, from the same view as the report and PDF.
        view = payload.consent_view
        if view:
            def _dump(name: str, data) -> None:
                zf.writestr(f"consent/{name}", json.dumps(data, indent=2, default=str))

            _dump("summary.json", {"status": view.get("status"), "tiles": view.get("tiles")})
            _dump("region-applicability.json", {
                "status": view.get("status"),
                "frameworks": view.get("frameworks"),
                "applicability": (payload.consent or {}).get("applicability", {}),
            })
            _dump("banner-controls.json", view.get("controls", []))
            _dump("network-classified.json", view.get("network", {}))
            _dump("cookies-before-consent.json", view.get("cookies", []))
            _dump("scan-pipeline.json", {"pipeline": view.get("pipeline", []), "legs": view.get("legs", []),
                                         "scan_id": (view.get("status") or {}).get("scan_id")})

        # Cookie Scanner: JSON + CSV.
        if payload.cookie_inventory:
            from reports.cookie_view import inventory_csv

            zf.writestr("cookies/cookie-inventory.json",
                        json.dumps(payload.cookie_inventory, indent=2, default=str))
            zf.writestr("cookies/cookie-inventory.csv", inventory_csv(payload.cookie_inventory))

        # Journey Map screenshots: evidence/journey/<page>/interaction_NNN_{before,highlighted,after}.png
        jv = payload.journey_view
        if jv:
            from reports.journey_view import screenshot_file

            added = set()
            for row in jv.get("interactions") or []:
                for kind, url in (row.get("screenshots") or {}).items():
                    disk = screenshot_file(url)
                    if not disk or disk in added:
                        continue
                    added.add(disk)
                    page_dir = (row.get("page_path") or "/").strip("/").replace("/", "_") or "home"
                    name = f"evidence/journey/{page_dir}/interaction_{int(row.get('index') or 0):03d}_{kind}.png"
                    with open(disk, "rb") as fh:
                        zf.writestr(name, fh.read())
            for page in jv.get("pages") or []:
                disk = screenshot_file(page.get("screenshot"))
                if disk:
                    page_dir = (page.get("path") or "/").strip("/").replace("/", "_") or "home"
                    with open(disk, "rb") as fh:
                        zf.writestr(f"evidence/journey/{page_dir}/page.png", fh.read())
            zf.writestr("evidence/journey/journey.json", json.dumps({
                "health": {"score": jv.get("score"), "counts": jv.get("counts"), "rates": jv.get("rates")},
                "interactions": jv.get("interactions"), "journeys": (jv.get("map") or {}).get("journeys"),
                "forms": jv.get("forms"), "downloads": jv.get("downloads"), "findings": jv.get("findings"),
            }, indent=2, default=str))

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
