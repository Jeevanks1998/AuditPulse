"""
Fetches and parses the site's pages:
  robots.py      - robots.txt (cached per host)
  sitemap.py     - sitemap URLs
  parser.py      - HTML -> ParsedPage (parsed once per page)
  links.py       - links found on a page
  extractor.py   - page measurements
  screenshots.py - optional full-page screenshots
  crawler.py     - crawl_site(): breadth-first crawl tying it together
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
