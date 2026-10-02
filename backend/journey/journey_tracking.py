"""
journey/journey_tracking.py

Connects each tested interaction to the analytics activity it produced:

    interaction → browser action → network requests + dataLayer pushes
                → vendor (GA4 / GTM / Piano / Adobe / Meta / …) → event

Reuses analytics/runtime.py — the same vendor classifiers (GA4, GTM,
gtag, Adobe, Piano, Clarity, Hotjar, Meta, LinkedIn, TikTok), the GA4
batched-POST parsing and the dataLayer hook — instead of re-implementing
any vendor logic here.

For every interaction it answers:
  * was an analytics request generated, which vendor, which event,
    which parameters?
  * was the event duplicated?
  * was the event missing?
  * did it happen before or after the interaction?
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from analytics.runtime import (
    DATALAYER_BINDING,
    DATALAYER_HOOK_JS,
    LIFECYCLE_EVENTS,
    VENDOR_LABELS,
    classify_analytics_request,
    event_parameters,
)

TRACKED = "tracked"
NOT_TRACKED = "not_tracked"
DUPLICATE = "duplicate"
NOT_TESTED = "not_tested"
NOT_APPLICABLE = "not_applicable"


@dataclass
class TrackedEvent:
    t: float                   # monotonic seconds
    source: str                # "network" | "dataLayer"
    vendor: str                # "ga4" | "gtm" | "dataLayer" | …
    event: Optional[str]
    url: str = ""
    params: Dict[str, str] = field(default_factory=dict)

    @property
    def is_lifecycle(self) -> bool:
        return (self.event or "") in LIFECYCLE_EVENTS or not self.event

    def as_dict(self) -> dict:
        return {"source": self.source, "vendor": self.vendor,
                "vendor_label": VENDOR_LABELS.get(self.vendor, "dataLayer" if self.vendor == "dataLayer" else self.vendor),
                "event": self.event, "params": dict(list(self.params.items())[:12]),
                "url": self.url[:300]}


class TrackingCapture:
    """Records every analytics hit and dataLayer push in a browser context."""

    def __init__(self) -> None:
        self.events: List[TrackedEvent] = []

    async def attach(self, context) -> None:
        await context.expose_binding(DATALAYER_BINDING, self._on_datalayer)
        await context.add_init_script(DATALAYER_HOOK_JS)
        context.on("request", self._on_request)

    def _on_request(self, request) -> None:
        try:
            post = request.post_data
        except Exception:  # noqa: BLE001 — binary bodies
            post = None
        for hit in classify_analytics_request(request.url, post):
            line = ""
            if post and hit.event_name:
                line = next((ln for ln in post.splitlines() if f"en={hit.event_name}" in ln), "")
            self.events.append(TrackedEvent(
                t=time.monotonic(), source="network", vendor=hit.vendor_key or "unknown",
                event=hit.event_name, url=request.url, params=event_parameters(request.url, line),
            ))

    def _on_datalayer(self, _source, payload: str) -> None:
        try:
            data = json.loads(payload)
        except Exception:  # noqa: BLE001
            return
        params = {k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v))[:200]
                  for k, v in (data.get("params") or {}).items() if k != "event"}
        self.events.append(TrackedEvent(
            t=time.monotonic(), source="dataLayer", vendor="dataLayer",
            event=data.get("event"), url=data.get("url") or "", params=params,
        ))

    def mark(self) -> float:
        return time.monotonic()

    def between(self, start: float, end: Optional[float] = None) -> List[TrackedEvent]:
        end = end if end is not None else time.monotonic() + 1
        return [e for e in self.events if start <= e.t <= end]

    @property
    def vendors_seen(self) -> List[str]:
        return sorted({e.vendor for e in self.events if e.source == "network"})


@dataclass
class InteractionTracking:
    status: str = NOT_TESTED          # tracked | not_tracked | duplicate | not_tested | not_applicable
    events: List[dict] = field(default_factory=list)          # interaction events (after the action)
    lifecycle_events: List[dict] = field(default_factory=list)  # page_view etc. caused by navigation
    vendors: List[str] = field(default_factory=list)
    duplicates: List[str] = field(default_factory=list)
    before_action: List[dict] = field(default_factory=list)     # same-name events seen before the action
    note: str = ""

    def as_dict(self) -> dict:
        return {"status": self.status, "events": self.events, "lifecycle_events": self.lifecycle_events,
                "vendors": self.vendors, "duplicates": self.duplicates,
                "before_action": self.before_action, "note": self.note}


def evaluate_interaction(
    capture: TrackingCapture,
    action_started: float,
    window_end: float,
    pre_window_start: Optional[float] = None,
    analytics_present: bool = True,
) -> InteractionTracking:
    """
    Attributes analytics activity to one interaction: everything from the
    moment of the action to the end of its settle window. Lifecycle events
    (page_view, gtm.js, session_start…) prove the destination page is
    tracked, not that the *interaction* was — they're reported separately.
    """
    window = capture.between(action_started, window_end)
    interaction = [e for e in window if not e.is_lifecycle]
    lifecycle = [e for e in window if e.is_lifecycle and e.event]

    result = InteractionTracking(
        events=[e.as_dict() for e in interaction[:20]],
        lifecycle_events=[e.as_dict() for e in lifecycle[:10]],
        vendors=sorted({e.vendor for e in interaction}),
    )

    # Duplicate: the same vendor sent the same event more than once for one action.
    counts: Dict[str, int] = {}
    for e in interaction:
        if e.source != "network":
            continue
        key = f"{e.vendor}:{e.event}"
        counts[key] = counts.get(key, 0) + 1
    result.duplicates = sorted(k for k, n in counts.items() if n > 1)

    if pre_window_start is not None:
        names = {e.event for e in interaction}
        before = [e for e in capture.between(pre_window_start, action_started) if e.event in names and not e.is_lifecycle]
        result.before_action = [e.as_dict() for e in before[:5]]

    if interaction:
        result.status = DUPLICATE if result.duplicates else TRACKED
    else:
        result.status = NOT_TRACKED
        result.note = ("No analytics event was observed for this interaction"
                       + (" (the destination page sent a page_view)." if lifecycle else ".")
                       + ("" if analytics_present else " No analytics vendor was observed on the site at all."))
    return result


def site_vendor_summary(capture: TrackingCapture) -> dict:
    vendors: Dict[str, dict] = {}
    for e in capture.events:
        v = vendors.setdefault(e.vendor, {"vendor": e.vendor,
                                          "label": VENDOR_LABELS.get(e.vendor, e.vendor),
                                          "hits": 0, "events": {}})
        v["hits"] += 1
        if e.event:
            v["events"][e.event] = v["events"].get(e.event, 0) + 1
    return {"vendors": list(vendors.values()),
            "analytics_present": any(e.source == "network" for e in capture.events)}
