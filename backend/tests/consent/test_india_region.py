"""India / DPDP detection for global .com sites whose homepage is generic
(e.g. axagbs.com): the evidence is on linked pages, documents and link URLs."""

from consent.consent_score import _dpdp_notice_check, build_dpdp_assessment
from consent.region import REGION_EU, REGION_IN, detect_region, refine_region
from consent.site_evidence import SiteDocument, SiteEvidence
from crawler.parser import parse_html

HOME = """<html lang="en"><body><header><a href="/about-us">About</a><a href="/policies">Policies</a></header>
<main><h1>Shaping the future of insurance operations</h1><p>We are a global business services company.</p>
<a href="/news/axa-opens-new-office-space-in-pune-expands-its-global-business-services-center">News</a>
<a href="/news/axa-gbs-celebrates-30-years-in-india">30 years</a></main></body></html>"""

NOTICE = """Website Privacy Notice. This notice explains what personal data we collect and the purposes for which
we use it. Your rights: you have the right to access, correct and erase your data and to withdraw consent.
Grievance Officer: Jane Doe, email grievance.officer@example.com. This notice is issued under the Digital
Personal Data Protection Act, 2023."""


def _page():
    return parse_html("https://www.axagbs.com/", HOME)


def test_generic_homepage_alone_is_unknown_without_site_evidence():
    page = parse_html("https://www.axagbs.com/", "<html lang='en'><body><h1>Insurance operations</h1></body></html>")
    assert detect_region("https://www.axagbs.com/", page).regions == []


def test_india_from_linked_pages_and_documents():
    site = SiteEvidence(
        documents=[SiteDocument(url="https://www.axagbs.com/policies", kind="policy",
                                text="Policies. Form MGT-7 Annual Return 2024-25. CSR Policy.")],
        link_urls=["https://axa-gbs.cdn.prismic.io/axa-gbs/x_FormMGT-7AnnualReturn2024-25.pdf"],
    )
    result = detect_region("https://www.axagbs.com/", _page(), site=site)
    assert result.regions[0] == REGION_IN
    assert "dpdp" in result.frameworks
    ev = " | ".join(result.evidence)
    assert "Indian office location" in ev and "MGT" in ev


def test_repeated_evidence_counts_once():
    # Ten pages mentioning Pune are still one office location (25), plus
    # "India" (15): 40 < threshold, so no decision from that alone.
    site = SiteEvidence(documents=[SiteDocument(url=f"https://x.com/p{i}", kind="about", text="Our office in Pune")
                                   for i in range(10)])
    page = parse_html("https://x.com/", "<html><body>Hello</body></html>")
    r = detect_region("https://x.com/", page, site=site)
    assert r.scores.get(REGION_IN, 0) == 25 and r.regions == []


def test_opt_in_banner_does_not_override_india():
    class RT:
        available = True
        banner = {"banner_detected": True, "text_excerpt": "We use cookies"}
        preference_panel = None

        class C:
            def __init__(self, label): self.label = label
        controls = [C("Reject all"), C("Accept all")]

    site = SiteEvidence(documents=[SiteDocument(url="https://www.axagbs.com/policies", kind="policy",
                                                text="Form MGT-7 annual return")])
    r = refine_region(detect_region("https://www.axagbs.com/", _page(), site=site), RT())
    assert r.regions[0] == REGION_IN
    assert REGION_EU not in r.regions  # 25 for the opt-in pattern stays under the threshold


def test_dpdp_notice_checks_pass_on_good_notice():
    site = SiteEvidence(documents=[SiteDocument(url="https://x.com/privacy.pdf", kind="notice", text=NOTICE, is_pdf=True)])
    for key in ("notice_purpose_stated", "grievance_contact", "notice_rights_described", "dpdp_referenced"):
        passed, ev = _dpdp_notice_check(key, site)
        assert passed is True, key
        assert ev["notice"].endswith("privacy.pdf")


def test_dpdp_notice_checks_fail_and_not_tested():
    bad = SiteEvidence(documents=[SiteDocument(url="https://x.com/privacy", kind="notice", text="We like cookies.")])
    assert _dpdp_notice_check("grievance_contact", bad)[0] is False
    assert _dpdp_notice_check("grievance_contact", SiteEvidence())[0] is None


def test_dpdp_assessment_includes_notice_checks():
    class Tech:
        def get(self, key):
            return None
    a = build_dpdp_assessment(Tech(), SiteEvidence(documents=[SiteDocument(url="u", kind="notice", text=NOTICE)]))
    assert a["checks"]["grievance_contact"] is True
    assert "grievance_contact" in a["order"] and "grievance_contact" in a["labels"]
