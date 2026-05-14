"""
Generic university scout.

Reads `config/universities.yaml` and produces one `UniversityScout` instance
per entry. Each entry can use one of two fetchers:

  fetcher: requests    — fast, lightweight, works for server-rendered HTML.
  fetcher: playwright  — slow (~10s/site), spins up headless Chromium.
                         Use this for JS-rendered portals (Workday, some
                         single-page-app career sites). Optional config:
                         `wait_for_selector` lets you wait until a specific
                         CSS selector is present before grabbing HTML.

NOTE on Playwright + GitHub Actions: many university WAFs block requests
from cloud IP ranges (Azure, AWS) regardless of browser. If a site returns
403 even with Playwright, you'll see it in source-health. The remediation
is usually to find an alternate feed (Interfolio, RSS, the institution's
own RSS, or an aggregator that already indexes that university).

A `must_match` pre-filter on the title cheaply discards obviously-irrelevant
listings before the LLM relevance pass, to save API calls.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup

from core.models import Posting
from scouts import Scout


logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30           # seconds, for plain requests
PLAYWRIGHT_TIMEOUT = 60_000    # milliseconds, page-load budget
PLAYWRIGHT_WAIT_AFTER_LOAD = 2 # seconds; extra settle time for late XHRs

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

MAX_RESULTS_PER_UNIVERSITY = 100  # safety cap


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_university_scouts(config_path: Path) -> list["UniversityScout"]:
    """Read universities.yaml and return one scout per entry."""
    config_path = Path(config_path)
    if not config_path.exists():
        logger.warning("No universities config at %s", config_path)
        return []

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    entries = data.get("universities", [])
    scouts = []
    for entry in entries:
        try:
            scouts.append(UniversityScout(entry))
        except KeyError as e:
            logger.error(
                "Skipping malformed university entry %r (missing key %s)",
                entry.get("name"), e,
            )
    return scouts


# ---------------------------------------------------------------------------
# University scout
# ---------------------------------------------------------------------------

class UniversityScout(Scout):
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.display_name = config["name"]
        self.jobs_url = config["jobs_url"]
        self.posting_selector = config["posting_selector"]
        self.title_selector = config.get("title_selector", "a")
        self.link_selector = config.get("link_selector", "a")
        self.description_selector = config.get("description_selector")
        self.location_selector = config.get("location_selector")
        self.must_match: list[str] = [
            s.lower() for s in (config.get("must_match") or [])
        ]
        self.fetcher = config.get("fetcher", "requests").lower()
        # Playwright-specific:
        self.wait_for_selector: str | None = config.get("wait_for_selector")
        self.scroll_to_bottom: bool = bool(config.get("scroll_to_bottom", False))

        self.name = f"university:{self.display_name}"

    def fetch(self) -> list[Posting]:
        if self.fetcher == "playwright":
            html = self._fetch_playwright(self.jobs_url)
        else:
            html = self._fetch_requests(self.jobs_url)
        return self._parse(html)[:MAX_RESULTS_PER_UNIVERSITY]

    # ---------- fetchers ----------

    def _fetch_requests(self, url: str) -> str:
        resp = requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.7",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.text

    def _fetch_playwright(self, url: str) -> str:
        """Fetch a JavaScript-rendered page using headless Chromium.

        Optional config knobs that help with Workday and similar SPAs:
          wait_for_selector: a CSS selector that must appear before we grab
            the HTML. For Workday this is typically '[data-automation-id="jobTitle"]'.
          scroll_to_bottom: scroll to trigger lazy-loaded results before
            collecting HTML (some portals only render visible rows).
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RuntimeError(
                "Playwright not installed. Add 'playwright' to requirements.txt "
                "and run `playwright install chromium` (the GitHub Actions "
                "workflow does this automatically)."
            ) from e

        logger.info("[playwright] %s — fetching %s", self.display_name, url)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(user_agent=USER_AGENT)
                page = ctx.new_page()
                resp = page.goto(url, timeout=PLAYWRIGHT_TIMEOUT,
                                 wait_until="domcontentloaded")
                if resp is None:
                    raise RuntimeError("playwright: no response object")
                if resp.status >= 400:
                    raise RuntimeError(
                        f"playwright: HTTP {resp.status} from {url}"
                    )

                # If config specified a selector to wait for, honor it.
                if self.wait_for_selector:
                    try:
                        page.wait_for_selector(
                            self.wait_for_selector,
                            timeout=PLAYWRIGHT_TIMEOUT,
                        )
                    except Exception as e:
                        # Surface this clearly — usually means the selector
                        # is wrong or the site changed its DOM.
                        raise RuntimeError(
                            f"playwright: wait_for_selector "
                            f"{self.wait_for_selector!r} never appeared "
                            f"on {url}: {e}"
                        ) from e

                if self.scroll_to_bottom:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1500)

                # A short settle pause helps catch late-firing XHRs that
                # finish after domcontentloaded but before networkidle.
                page.wait_for_timeout(PLAYWRIGHT_WAIT_AFTER_LOAD * 1000)
                return page.content()
            finally:
                browser.close()

    # ---------- parser ----------

    def _parse(self, html: str) -> list[Posting]:
        soup = BeautifulSoup(html, "lxml")
        postings: list[Posting] = []

        for card in soup.select(self.posting_selector):
            try:
                p = self._parse_card(card)
            except Exception as e:
                logger.debug("%s: card parse error: %s", self.display_name, e)
                continue
            if not p:
                continue
            if self.must_match and not self._title_matches(p.title):
                continue
            postings.append(p)

        return postings

    def _parse_card(self, card) -> Posting | None:
        link_el = card.select_one(self.link_selector)
        title_el = card.select_one(self.title_selector)
        if not link_el or not title_el:
            return None

        title = title_el.get_text(" ", strip=True)
        href = link_el.get("href")
        if not title or not href:
            return None
        url = urljoin(self.jobs_url, href)

        description = ""
        if self.description_selector:
            d = card.select_one(self.description_selector)
            if d:
                description = d.get_text(" ", strip=True)

        location = None
        if self.location_selector:
            loc = card.select_one(self.location_selector)
            if loc:
                location = loc.get_text(" ", strip=True)

        return Posting(
            source=self.name,
            title=title,
            institution=self.display_name,
            url=url,
            description=description,
            location=location,
        )

    def _title_matches(self, title: str) -> bool:
        t = title.lower()
        return any(kw in t for kw in self.must_match)
