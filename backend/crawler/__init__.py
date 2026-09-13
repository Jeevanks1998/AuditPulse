"""
crawler/

The real crawl/parse/extract pipeline that backs an audit run. This is
the package `services.audit_service.run_audit_pipeline` swaps in for
`_generate_placeholder_findings` once a run needs to look at an actual
website instead of rolling random scores.

Modules:
    robots.py      - async robots.txt fetch/parse/cache, per hostname
    sitemap.py      - sitemap.xml / sitemapindex discovery + flattening
    parser.py       - raw HTML -> ParsedPage (BeautifulSoup, done once per page)
    links.py        - ParsedPage -> resolved/classified Link objects
    extractor.py    - ParsedPage + Link[] -> PageSignals (the flat dict
                       the SEO/accessibility scoring reads)
    screenshots.py  - optional Playwright full-page screenshot capture
    crawler.py      - Crawler/crawl_site: the orchestrator tying all of
                       the above into one breadth-first crawl

Typical usage (from services.audit_service or a Celery task):

    from crawler import crawl_site

    result = await crawl_site(audit.url, max_pages=audit.max_pages, depth=audit.depth)
    for page in result.ok_pages:
        ...  # page.signals feeds SEO/accessibility scoring, page.links feeds link checks
"""

from crawler.crawler import Crawler, CrawlResult, PageResult, crawl_site
from crawler.extractor import PageSignals, extract_signals
from crawler.links import Link, extract_links, same_site_targets
from crawler.parser import ParsedPage, parse_html
from crawler.robots import RobotsChecker
from crawler.sitemap import discover_sitemap_urls

__all__ = [
    "Crawler",
    "CrawlResult",
    "PageResult",
    "crawl_site",
    "PageSignals",
    "extract_signals",
    "Link",
    "extract_links",
    "same_site_targets",
    "ParsedPage",
    "parse_html",
    "RobotsChecker",
    "discover_sitemap_urls",
]
