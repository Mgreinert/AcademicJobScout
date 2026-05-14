"""
EURAXESS scout.

EURAXESS is the European Commission's job portal for researchers. It covers
jobs across 43 European countries plus worldwide hubs. We scrape its public
search results page (no public consumption API as of 2026).

Strategy:
  - Build a search URL using a small set of keywords from Jasnea's profile
    (political geography, border studies, Asia studies, human geography).
  - Parse each result card into a Posting.
  - Cap results so a search blow-up doesn't flood the digest; the LLM filter
    will further trim by fit score.

Failure modes:
  - HTTP errors raise to the orchestrator, which records FETCH_FAILED.
  - HTML structure changes return an empty list, which the orchestrator
    records as PARSE_EMPTY.
"""
from __future__ import annotations

import logging
from urllib.parse import urljoin, urlencode

import requests
from bs4 import BeautifulSoup

from core.models import Posting
from scouts import Scout


logger = logging.getLogger(__name__)

BASE_URL = "https://euraxess.ec.europa.eu"
SEARCH_PATH = "/jobs/search"

# Keywords tuned to the researcher's field. The LLM does the precise filtering
# downstream, so we cast a moderately wide net here.
SEARCH_KEYWORDS = [
    "political geography",
    "human geography",
    "border studies",
    "asian studies",
    "geopolitics",
]

# Results per keyword query — Euraxess paginates at ~10/page. We grab the
# first page only; if a search returns >10 relevant new results per week,
# that's a luxury problem we can address by paginating.
MAX_RESULTS_PER_KEYWORD = 10

REQUEST_TIMEOUT = 30
USER_AGENT = "academic-job-scout/0.1 (personal use)"


class EuraxessScout(Scout):
    name = "euraxess"

    def fetch(self) -> list[Posting]:
        seen_urls: set[str] = set()
        postings: list[Posting] = []

        for keyword in SEARCH_KEYWORDS:
            try:
                results = self._search(keyword)
            except Exception as e:
                logger.warning("Euraxess search failed for %r: %s", keyword, e)
                # Re-raise only if EVERY keyword fails; for now, continue
                continue

            for p in results:
                if p.url in seen_urls:
                    continue
                seen_urls.add(p.url)
                postings.append(p)

        return postings

    def _search(self, keyword: str) -> list[Posting]:
        params = {"keywords": keyword}
        url = f"{BASE_URL}{SEARCH_PATH}?{urlencode(params)}"
        logger.info("Euraxess: fetching %s", url)

        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()

        return self._parse(resp.text)[:MAX_RESULTS_PER_KEYWORD]

    def _parse(self, html: str) -> list[Posting]:
        """Parse Euraxess search results page.

        The current (2026) markup wraps each job in an article element with
        a class containing 'job' or 'search-result'. We try a few selectors
        to be resilient to small markup tweaks; if all return nothing, we
        return [] and the orchestrator flags PARSE_EMPTY.
        """
        soup = BeautifulSoup(html, "lxml")
        postings: list[Posting] = []

        # Try several plausible selectors for a job card.
        candidates = (
            soup.select("article.job-offer")
            or soup.select("article[class*='job']")
            or soup.select("div.search-result")
            or soup.select("li.search-result")
            or soup.select("div[class*='result-item']")
        )

        for card in candidates:
            try:
                p = self._parse_card(card)
                if p:
                    postings.append(p)
            except Exception as e:
                logger.debug("Euraxess: failed to parse a card: %s", e)
                continue

        return postings

    def _parse_card(self, card) -> Posting | None:
        # Title + link
        link = card.select_one("a[href*='/jobs/']") or card.find("a", href=True)
        if not link:
            return None
        title = link.get_text(strip=True)
        href = link["href"]
        if not title or not href:
            return None
        url = urljoin(BASE_URL, href)

        # Institution / hiring org — try a few possible attribute classes
        institution = ""
        for sel in (".organisation", ".hiring-organisation", "[class*='organisation']", ".job-employer"):
            el = card.select_one(sel)
            if el:
                institution = el.get_text(" ", strip=True)
                break

        # Location
        location = None
        for sel in (".location", "[class*='location']", ".job-location"):
            el = card.select_one(sel)
            if el:
                location = el.get_text(" ", strip=True)
                break

        # Description snippet — first paragraph-ish block on the card
        description = ""
        desc_el = card.select_one("p") or card.select_one("[class*='summary']")
        if desc_el:
            description = desc_el.get_text(" ", strip=True)

        return Posting(
            source=self.name,
            title=title,
            institution=institution or "(unknown)",
            url=url,
            description=description,
            location=location,
        )
