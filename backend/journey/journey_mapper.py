"""
journey/journey_mapper.py

Builds the Customer Journey Map purely from what journey_scanner discovered
and journey_interactions tested — no assumed pages, steps or funnels.

Three views of the same data:

  site_tree   pages as discovered (homepage → pages it links to → …), each
              with its interaction counts, built from the real "found via
              link X on page Y" relationships
  graph       nodes (pages + key interactions) and edges (page→page links,
              page→interaction, interaction→destination page / form)
  journeys    for every conversion-type interaction: the shortest discovered
              path from the start page to it, then where it leads, e.g.

                  Homepage → Services → Product → [CTA] Request quote
                           → Quote → [Form] Quote form → [Form Submit] Send

Every node carries: page, interaction, interaction type, test status,
tracking status, screenshot, evidence text and issue ids (QA fills those).
"""

from __future__ import annotations

from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

from journey.journey_interactions import (
    CLASS_LABELS,
    CONVERSION_CLASSES,
    FORM,
    FORM_SUBMIT,
    Interaction,
)
from journey.journey_scanner import PageScan, normalize_url

MAX_JOURNEYS = 25


def _path_label(url: str) -> str:
    p = urlparse(url)
    return (p.path or "/") + (("?" + p.query) if p.query else "")


def _page_node(page: PageScan, shots: Dict[str, Optional[str]], interactions: List[Interaction]) -> dict:
    mine = [i for i in interactions if normalize_url(i.page_url) == normalize_url(page.url)]
    counts: Dict[str, int] = {}
    for i in mine:
        counts[i.classification] = counts.get(i.classification, 0) + 1
    return {
        "id": f"page:{normalize_url(page.url)}",
        "kind": "page",
        "url": page.url,
        "path": _path_label(page.url),
        "title": page.title or _path_label(page.url),
        "depth": page.depth,
        "parent": f"page:{normalize_url(page.parent_url)}" if page.parent_url else None,
        "via_label": page.via_label,
        "status": page.status,
        "error": page.error,
        "screenshot": shots.get(normalize_url(page.url)),
        "interaction_count": len(mine),
        "counts": counts,
    }


def _interaction_node(it: Interaction) -> dict:
    tracking = it.tracking or {}
    return {
        "id": f"int:{it.index}",
        "kind": "interaction",
        "index": it.index,
        "page": it.page_url,
        "path": _path_label(it.page_url),
        "label": it.label,
        "type": it.classification,
        "type_label": it.classification_label,
        "pattern": it.pattern,
        "test_status": it.status,
        "outcome": it.outcome,
        "observed": it.observed,
        "tracking_status": tracking.get("status", "not_tested"),
        "tracking_events": [f"{e.get('vendor_label')}: {e.get('event')}" for e in (tracking.get("events") or [])][:6],
        "screenshots": it.screenshots,
        "destination": it.destination,
        "final_url": it.final_url,
        "issues": [],
    }


def _is_gap(node: Optional[dict]) -> bool:
    """A tracking gap = the interaction worked when tested, but no analytics event was seen."""
    return bool(node) and node.get("kind") == "interaction" and node.get("test_status") == "success" \
        and node.get("tracking_status") == "not_tracked"


def build_journey_map(
    pages: List[PageScan],
    interactions: List[Interaction],
    page_shots: Dict[str, Optional[str]],
    start_url: str,
) -> dict:
    page_by_url = {normalize_url(p.url): p for p in pages}
    page_nodes = {f"page:{u}": _page_node(p, page_shots, interactions) for u, p in page_by_url.items()}

    # Key interactions: conversion-type, forms, and anything actually tested
    # (repeats of the same element on other pages are folded into the first).
    key_interactions = [i for i in interactions
                        if i.duplicate_of is None and (i.classification in CONVERSION_CLASSES or i.classification == FORM
                                                       or i.tested)]
    int_nodes = {f"int:{i.index}": _interaction_node(i) for i in key_interactions}

    edges: List[dict] = []
    seen_edges = set()

    def edge(src: str, dst: str, kind: str, label: str = "") -> None:
        key = (src, dst, kind)
        if key in seen_edges or src == dst:
            return
        seen_edges.add(key)
        edges.append({"from": src, "to": dst, "kind": kind, "label": label[:80]})

    for p in pages:
        if p.parent_url:
            edge(f"page:{normalize_url(p.parent_url)}", f"page:{normalize_url(p.url)}", "discovered_via", p.via_label or "")
        for out in p.links_out:
            if f"page:{out}" in page_nodes:
                edge(f"page:{normalize_url(p.url)}", f"page:{out}", "links_to")

    for i in key_interactions:
        nid = f"int:{i.index}"
        edge(f"page:{normalize_url(i.page_url)}", nid, "has_interaction", i.classification_label)
        target = None
        if i.final_url and normalize_url(i.final_url) in page_by_url:
            target = normalize_url(i.final_url)
        elif i.destination and urlparse(i.destination).scheme in ("http", "https"):
            d = normalize_url(urljoin(i.page_url, i.destination))
            if d in page_by_url:
                target = d
        if target:
            edge(nid, f"page:{target}", "leads_to")

    # --- site tree (discovered parent → child) ---------------------------------
    children: Dict[Optional[str], List[str]] = {}
    for nid, n in page_nodes.items():
        children.setdefault(n["parent"], []).append(nid)

    def tree(nid: str, depth: int = 0) -> dict:
        n = page_nodes[nid]
        kids = sorted(children.get(nid, []), key=lambda k: page_nodes[k]["path"])
        page_ints = [int_nodes[f"int:{i.index}"] for i in key_interactions
                     if f"page:{normalize_url(i.page_url)}" == nid]
        return {"node": n["id"], "path": n["path"], "title": n["title"],
                "interactions": [x["id"] for x in page_ints][:12],
                "children": [tree(k, depth + 1) for k in kids] if depth < 6 else []}

    root_id = f"page:{normalize_url(start_url)}"
    roots = [root_id] if root_id in page_nodes else [k for k in children.get(None, [])]
    site_tree = [tree(r) for r in roots]

    # --- conversion journeys ---------------------------------------------------
    def page_chain(url: str) -> List[str]:
        chain, cur, guard = [], page_by_url.get(normalize_url(url)), 0
        while cur is not None and guard < 10:
            chain.insert(0, f"page:{normalize_url(cur.url)}")
            cur = page_by_url.get(normalize_url(cur.parent_url)) if cur.parent_url else None
            guard += 1
        return chain

    forms_by_page: Dict[str, List[Interaction]] = {}
    for i in key_interactions:
        if i.classification in (FORM, FORM_SUBMIT):
            forms_by_page.setdefault(normalize_url(i.page_url), []).append(i)
    for lst in forms_by_page.values():   # the form comes before its submit step
        lst.sort(key=lambda i: (i.classification != FORM, i.index))

    journeys: List[dict] = []
    conv = [i for i in key_interactions if i.classification in CONVERSION_CLASSES and i.classification != FORM_SUBMIT]
    conv.sort(key=lambda i: (-i.importance, i.status != "success", i.index))
    for i in conv[:MAX_JOURNEYS]:
        steps = page_chain(i.page_url) + [f"int:{i.index}"]
        target = None
        if i.final_url and normalize_url(i.final_url) in page_by_url:
            target = normalize_url(i.final_url)
        elif i.destination and urlparse(i.destination).scheme in ("http", "https"):
            d = normalize_url(urljoin(i.page_url, i.destination))
            target = d if d in page_by_url else None
        if target and f"page:{target}" not in steps:
            steps.append(f"page:{target}")
            for f in forms_by_page.get(target, [])[:2]:
                steps.append(f"int:{f.index}")
        gaps = [s for s in steps if _is_gap(int_nodes.get(s))]
        journeys.append({
            "id": f"journey:{i.index}",
            "name": f"{CLASS_LABELS.get(i.classification, i.classification)}: {i.label}"[:120],
            "goal_type": i.classification,
            "steps": steps,
            "tracking_gaps": gaps,
            "tested": all(int_nodes.get(s, {}).get("test_status") in ("success", "skipped") for s in steps if s.startswith("int:")),
        })

    # Forms reached directly (not behind a discovered CTA) are journeys too.
    covered = {s for j in journeys for s in j["steps"]}
    for page_url, forms in forms_by_page.items():
        for f in forms:
            if f"int:{f.index}" in covered or f.classification != FORM or len(journeys) >= MAX_JOURNEYS:
                continue
            steps = page_chain(page_url) + [f"int:{f.index}"]
            journeys.append({
                "id": f"journey:{f.index}", "name": f"Form: {f.label}"[:120], "goal_type": FORM, "steps": steps,
                "tracking_gaps": [s for s in steps if _is_gap(int_nodes.get(s))],
                "tested": f.status in ("success", "skipped"),
            })

    nodes = {**page_nodes, **int_nodes}
    return {
        "start": root_id,
        "nodes": nodes,
        "edges": edges,
        "site_tree": site_tree,
        "journeys": journeys,
        "stats": {"pages": len(page_nodes), "key_interactions": len(int_nodes), "edges": len(edges),
                  "journeys": len(journeys)},
    }
