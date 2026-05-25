"""
EURAXESS scout.

EURAXESS is the European Commission's job portal for researchers.
It covers jobs across 40+ European countries plus worldwide hubs.

Strategy (revised in session #3):

  Euraxess respects URL-based filters (verified by hitting the filtered
  URL with a fresh requests.get and seeing "Search results (1)" come
  back). So instead of scraping the default search page and letting the
  LLM cut everything, we scrape a saved-filter URL covering Jasnea's
  actual fields: geography subtypes, Asian/regional/oriental studies,
  anthropology, political sciences, history subtypes, sociology,
  ethnology, plus a `tenure` keyword and the Job Offer filter. That
  narrows the result set from thousands to ~100-200 highly relevant
  postings.

  We paginate via &page=N (zero-indexed, Drupal convention), stopping
  when a page returns no postings. A MAX_PAGES safety cap prevents
  runaway loops if the parser starts returning false positives on every
  page (e.g. matching a header link as a posting).

  If Euraxess ever changes the filter taxonomy and these field IDs go
  stale, the scraper will quietly return fewer/no results -- surface
  via the source-health system.

Failure modes:
  - HTTP errors raise to the orchestrator (records FETCH_FAILED).
  - HTML structure changes return an empty list (PARSE_EMPTY).
"""
from __future__ import annotations

import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from core.models import Posting
from scouts import Scout


logger = logging.getLogger(__name__)

BASE_URL = "https://euraxess.ec.europa.eu"

# Saved-filter URL covering Jasnea's fields. 47 filters total: organisation
# type = Higher Education Institution, 44 research_field IDs (geography,
# area studies, anthropology, political sciences, history, sociology,
# ethnology, etc.), keywords=tenure, offer_type=job_offer. Sort by
# created date, descending. See STATUS.md for the field-ID breakdown.
SEARCH_URL = (
    "https://euraxess.ec.europa.eu/jobs/search"
    "?f%5B0%5D=job_organisation_type%3A531"
    "&f%5B1%5D=job_research_field%3A10"
    "&f%5B2%5D=job_research_field%3A15"
    "&f%5B3%5D=job_research_field%3A16"
    "&f%5B4%5D=job_research_field%3A19"
    "&f%5B5%5D=job_research_field%3A39"
    "&f%5B6%5D=job_research_field%3A94"
    "&f%5B7%5D=job_research_field%3A100"
    "&f%5B8%5D=job_research_field%3A109"
    "&f%5B9%5D=job_research_field%3A110"
    "&f%5B10%5D=job_research_field%3A113"
    "&f%5B11%5D=job_research_field%3A132"
    "&f%5B12%5D=job_research_field%3A133"
    "&f%5B13%5D=job_research_field%3A140"
    "&f%5B14%5D=job_research_field%3A142"
    "&f%5B15%5D=job_research_field%3A144"
    "&f%5B16%5D=job_research_field%3A150"
    "&f%5B17%5D=job_research_field%3A152"
    "&f%5B18%5D=job_research_field%3A197"
    "&f%5B19%5D=job_research_field%3A198"
    "&f%5B20%5D=job_research_field%3A199"
    "&f%5B21%5D=job_research_field%3A208"
    "&f%5B22%5D=job_research_field%3A209"
    "&f%5B23%5D=job_research_field%3A210"
    "&f%5B24%5D=job_research_field%3A211"
    "&f%5B25%5D=job_research_field%3A212"
    "&f%5B26%5D=job_research_field%3A213"
    "&f%5B27%5D=job_research_field%3A214"
    "&f%5B28%5D=job_research_field%3A215"
    "&f%5B29%5D=job_research_field%3A216"
    "&f%5B30%5D=job_research_field%3A217"
    "&f%5B31%5D=job_research_field%3A218"
    "&f%5B32%5D=job_research_field%3A223"
    "&f%5B33%5D=job_research_field%3A228"
    "&f%5B34%5D=job_research_field%3A239"
    "&f%5B35%5D=job_research_field%3A246"
    "&f%5B36%5D=job_research_field%3A249"
    "&f%5B37%5D=job_research_field%3A289"
    "&f%5B38%5D=job_research_field%3A367"
    "&f%5B39%5D=job_research_field%3A373"
    "&f%5B40%5D=job_research_field%3A392"
    "&f%5B41%5D=job_research_field%3A395"
    "&f%5B42%5D=job_research_field%3A400"
    "&f%5B43%5D=job_research_field%3A410"
    "&f%5B44%5D=job_research_field%3A434"
    "&f%5B45%5D=keywords%3Atenure"
    "&f%5B46%5D=offer_type%3Ajob_offer"
    "&sort%5Bname%5D=created"
    "&sort%5Bdirection%5D=DESC"
)

REQUEST_TIMEOUT = 60  # Euraxess is sometimes slow on filtered queries
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
MAX_RESULTS = 150  # raised from 20 now that we paginate
MAX_PAGES = 10     # safety cap; ~20 postings/page => 200 max scanned


class EuraxessScout(Scout):
    name = "euraxess"

    def fetch(self) -> list[Posting]:
        all_postings: list[Posting] = []
        seen_urls: set[str] = set()

        # Use a Session so cookies set by Euraxess on page 0 (e.g. session
        # IDs or CSRF tokens used to validate pagination) persist across
        # subsequent page requests. Plain requests.get() discards them.
        session = requests.Session()
        session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.7",
        })

        prev_url: str | None = None
        for page in range(MAX_PAGES):
            page_url = SEARCH_URL if page == 0 else f"{SEARCH_URL}&page={page}"
            logger.info("Euraxess: fetching page %d (%s)", page, page_url[:80] + "...")

            # Polite delay between pages, and set Referer to the previous
            # page so Drupal pagination validators are happy.
            headers = {}
            if prev_url is not None:
                import time
                time.sleep(2)
                headers["Referer"] = prev_url

            try:
                resp = session.get(page_url, headers=headers, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
            except requests.RequestException as e:
                if page == 0:
                    # First page failure is fatal -- let it propagate.
                    raise
                # Mid-pagination failure: log and stop walking, return what
                # we have rather than failing the whole source.
                logger.warning("Euraxess: page %d failed (%s); stopping", page, e)
                break

            page_postings = self._parse(resp.text)
            if not page_postings:
                logger.info("Euraxess: page %d returned no postings; stopping", page)
                break

            new_count = 0
            for p in page_postings:
                if p.url in seen_urls:
                    continue
                seen_urls.add(p.url)
                all_postings.append(p)
                new_count += 1

            logger.info("Euraxess: page %d yielded %d new postings (%d on page)",
                        page, new_count, len(page_postings))

            # If the page had results but none were new (all already in
            # seen_urls), we've started seeing the same items -- stop.
            if new_count == 0:
                logger.info("Euraxess: page %d had no new postings; stopping", page)
                break

            prev_url = page_url

        return all_postings[:MAX_RESULTS]

    def _parse(self, html: str) -> list[Posting]:
        """Parse Euraxess search results page.

        Each posting is wrapped in <article class="ecl-content-item"> with
        the title and detail link inside <h3 class="ecl-content-block__title">.
        This is the EU Commission's ECL (Europa Component Library) design
        system and these class names are stable across Drupal updates.

        Anchoring on the article element excludes the sidebar filter chips,
        which were the source of the bug where filter names like "Cultural
        anthropology" were being scraped as postings.
        """
        soup = BeautifulSoup(html, "lxml")
        postings: list[Posting] = []

        for card in soup.select("article.ecl-content-item"):
            title_link = card.select_one("h3.ecl-content-block__title a")
            if not title_link:
                continue

            href = title_link.get("href", "")
            title = title_link.get_text(" ", strip=True)
            if not href or not title:
                continue

            url = urljoin(BASE_URL, href)
            institution, location, description = self._extract_metadata(card)

            postings.append(
                Posting(
                    source=self.name,
                    title=title,
                    institution=institution or "(unknown)",
                    url=url,
                    description=description,
                    location=location,
                )
            )

        return postings

    @staticmethod
    def _extract_metadata(card) -> tuple[str, str | None, str]:
        """Pull institution, location, description out of a card if possible."""
        institution, location, description = "", None, ""
        if card is None:
            return institution, location, description

        text = card.get_text(" | ", strip=True)
        # Euraxess cards typically read: "JOB | <Country> | <Org> | Posted on: ..."
        parts = [p.strip() for p in text.split("|") if p.strip()]
        for i, part in enumerate(parts):
            if part.lower() == "job" and i + 2 < len(parts):
                location = parts[i + 1]
                institution = parts[i + 2]
                break

        # Description = whatever paragraph-like text is on the card
        p = card.find("p")
        if p:
            description = p.get_text(" ", strip=True)[:500]

        return institution, location, description