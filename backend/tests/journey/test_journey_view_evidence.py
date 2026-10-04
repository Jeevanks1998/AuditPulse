"""Journey map is evidence-driven: analytics result split, safety reasons,
journey type/importance/status and the health breakdown all come from the
stored scan."""

from reports.journey_view import analytics_result, build_journey_view, safety_status


def _it(index, cls, status, events=(), tstatus=None, **kw):
    return {"index": index, "label": f"El {index}", "classification": cls,
            "classification_label": cls.upper(), "page_url": "https://ex.test/", "status": status,
            "importance": kw.pop("importance", 3), "safe": kw.pop("safe", True),
            "tracking": {"status": tstatus, "events": list(events)}, "screenshots": kw.pop("shots", {"before": "a.png"}),
            "duplicate_of": None, **kw}


NET = {"source": "network", "vendor": "ga4", "vendor_label": "GA4", "event": "click"}
DL = {"source": "dataLayer", "vendor": "dataLayer", "vendor_label": "dataLayer", "event": "click"}


def test_analytics_result_separates_sources():
    assert analytics_result(_it(1, "cta", "success", [NET], "tracked"))["key"] == "analytics_hit"
    assert analytics_result(_it(1, "cta", "success", [DL], "tracked"))["key"] == "datalayer"
    assert analytics_result(_it(1, "cta", "success", [NET, DL], "tracked"))["key"] == "both"
    assert analytics_result(_it(1, "cta", "success", [NET, NET], "duplicate"))["key"] == "duplicate"
    assert analytics_result(_it(1, "cta", "success", [], "not_tracked"))["key"] == "not_detected"
    r = analytics_result(_it(1, "purchase", "skipped", [], "not_tested"))
    assert r["key"] == "unable" and r["reason"]


def test_safety_status_explains_skips():
    s = safety_status(_it(1, "purchase", "skipped", unsafe_reason="purchase/payment action", safe=False))
    assert s["key"] == "not_executed" and "purchase/payment action" in s["label"]
    assert safety_status(_it(1, "cta", "success"))["key"] == "executed"
    assert safety_status(_it(1, "other", "not_tested"))["key"] == "not_selected"


def test_view_journeys_health_and_counts():
    ints = [
        _it(1, "cta", "failed", [], "not_tested"),
        _it(2, "download", "success", [], "not_tracked"),
        _it(3, "signup", "success", [DL], "tracked", importance=2),
    ]
    nodes = {"page:https://ex.test/": {"kind": "page", "path": "/"}}
    for i in ints:
        nodes[f"int:{i['index']}"] = {"kind": "interaction", "index": i["index"], "type_label": i["classification"],
                                      "label": i["label"], "test_status": i["status"],
                                      "tracking_status": i["tracking"]["status"]}
    journeys = [{"id": f"journey:{i['index']}", "name": i["label"], "goal_type": i["classification"],
                 "steps": ["page:https://ex.test/", f"int:{i['index']}"],
                 "tracking_gaps": [f"int:2"] if i["index"] == 2 else []} for i in reversed(ints)]
    view = build_journey_view({
        "available": True, "interactions": ints,
        "health": {"score": 50, "counts": {"pages_scanned": 1},
                   "rates": {"success_rate": 2 / 3, "conversion_tracking_coverage": 0.5, "evidence_rate": 1.0}},
        "journey_map": {"nodes": nodes, "journeys": journeys},
        "findings": [{"severity": "critical", "title": "Broken", "recommendation": "Fix"}],
    })
    js = view["map"]["journeys"]
    assert [j["status"] for j in js] == ["broken", "tracking_gap", "ok"]
    assert js[0]["goal_type_label"] == "CTA" and js[0]["importance"] == "high"
    assert js[2]["goal_type_label"] == "Signup" and js[2]["importance"] == "medium"
    v = view["tracking"]["validation"]
    assert v["datalayer"] == 1 and v["not_detected"] == 1 and v["analytics_hit"] == 0
    parts = {p["key"]: p for p in view["health_explained"]["parts"]}
    assert parts["tracking"]["points"] == 22.5 and parts["functional"]["weight"] == 35
    assert view["health_explained"]["critical_failures"] == 1
    assert "not recordings of real visitors" in view["provenance"]
    assert view["recommendations"] == [{"severity": "critical", "title": "Broken", "recommendation": "Fix"}]


def test_no_findings_means_no_recommendations():
    view = build_journey_view({"available": True, "interactions": [], "health": {"score": None},
                               "journey_map": {}, "findings": []})
    assert view["recommendations"] == [] and view["map"]["journeys"] == []
    assert view["health_explained"]["parts"] == []
