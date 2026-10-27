"""Duplicate detection: one hit each to two GA4 properties is dual tagging, not a duplicate (axa.it)."""

from journey.journey_tracking import DUPLICATE, TRACKED, TrackedEvent, TrackingCapture, evaluate_interaction


def _ga4(t, tid):
    return TrackedEvent(t=t, source="network", vendor="ga4", event="trovaagente",
                        url=f"https://www.google-analytics.com/g/collect?v=2&tid={tid}&en=trovaagente")


def test_two_properties_is_not_duplicate():
    cap = TrackingCapture()
    cap.events = [_ga4(1.0, "G-96VCPZE42Z"), _ga4(1.1, "G-416FH3Z0GR")]
    r = evaluate_interaction(cap, 0.5, 2.0)
    assert r.status == TRACKED and r.duplicates == []


def test_same_property_twice_is_duplicate():
    cap = TrackingCapture()
    cap.events = [_ga4(1.0, "G-96VCPZE42Z"), _ga4(1.1, "G-96VCPZE42Z")]
    r = evaluate_interaction(cap, 0.5, 2.0)
    assert r.status == DUPLICATE and r.duplicates == ["ga4:trovaagente"]
