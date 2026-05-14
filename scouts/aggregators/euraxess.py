"""
EURAXESS scout.

EURAXESS is the European Commission's job portal for researchers.
It covers jobs across 40+ European countries plus worldwide hubs.

Strategy (revised after first real run):

  Euraxess strips query parameters from the search URL — keyword filtering
  is done client-side via form interaction. Rather than reverse-engineer
  that, we just scrape the default search page (10 most recent postings
  across all fields), and let the LLM relevance filter handle the topical
  cut downstream. Signal-to-noise is worse than keyword filtering, but
  reliability is much better and the LLM is the real filter anyway.

  This means at most 10 postings/week from Euraxess, which is fine — the
  digest is curated, not exhaustive.

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
SEARCH_URL = f"{BASE_URL}/jobs/search"

REQUEST_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
MAX_RESULTS = 20


class EuraxessScout(Scout):
    name = "euraxess"

    def fetch(self) -> list[Posting]:
        logger.info("Euraxess: fetching %s", SEARCH_URL)
        resp = requests.get(
            SEARCH_URL,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.7",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return self._parse(resp.text)[:MAX_RESULTS]

    def _parse(self, html: str) -> list[Posting]:
        """Parse Euraxess search results page.

        The current markup (2026) presents each posting as a card with:
          - a link to the detail page (path includes 'jobs/' and an id)
          - title text inside the card
          - posted date, country, hiring org metadata

        We try multiple plausible selectors so small markup tweaks don't
        break us, and degrade to an empty list (PARSE_EMPTY) if all fail.
        """
        soup = BeautifulSoup(html, "lxml")
        postings: list[Posting] = []

        # Find all anchors that look like they point to a job detail page.
        # Euraxess detail URLs typically look like /jobs/<id>-<slug>
        job_links = soup.select("a[href^='/jobs/']")
        seen_hrefs: set[str] = set()

        for link in job_links:
            href = link.get("href", "")
            # Skip navigation links — only real postings have numeric IDs in path
            if not href or href in seen_hrefs:
                continue
            # Filter out obvious non-postings (search nav, filters)
            if href in ("/jobs", "/jobs/", "/jobs/search", "/jobs/posting"):
                continue
            seen_hrefs.add(href)

            title = link.get_text(" ", strip=True)
            if not title or len(title) < 8:
                # Page navigation links usually have very short text
                continue

            url = urljoin(BASE_URL, href)

            # Walk up to find the enclosing card and grab metadata from it
            card = link.find_parent(["article", "div", "li"]) or link.parent
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
