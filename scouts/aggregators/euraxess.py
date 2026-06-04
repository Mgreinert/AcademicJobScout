"""
EURAXESS scout.

EURAXESS is the European Commission's job portal for researchers.
It covers jobs across 40+ European countries plus worldwide hubs.

Strategy (revised in session #4):

  Euraxess respects URL-based filters, so we hit a saved-filter URL
  covering Jasnea's fields (geography subtypes, Asian/regional/oriental
  studies, anthropology, political sciences, history subtypes, sociology,
  ethnology, plus a `tenure` keyword and the Job Offer filter). That
  narrows the result set from thousands to ~100-200 highly relevant
  postings.

  PAGINATION (the session-#4 change):

  Building &page=N URLs with plain `requests` works from a residential
  IP but is silently ignored from cloud IP ranges (GitHub Actions, etc.):
  page 1 comes back identical to page 0. We confirmed across session #3
  that cookies (Session), inter-page delays, and Referer headers do not
  fix this -- it's IP-level behaviour on Euraxess's side, not something a
  request header can change.

  The fix: drive pagination with a real browser (Playwright). We load
  page 0, parse it, then click the ECL "next page" control and re-read
  the rendered DOM, repeating until there's no next control or a page
  yields no new postings. Because the page number is now browser
  navigation state rather than a query parameter we attach, the cloud-IP
  parameter-stripping no longer applies. This mirrors how the working
  CUNY / University of Washington Playwright scouts reach the same class
  of site from Actions.

  If Playwright is unavailable or the next-page control can't be found,
  we degrade to page-0-only (still returns the freshest postings) rather
  than failing the whole source.

Failure modes:
  - HTTP errors / load failures on page 0 raise (records FETCH_FAILED).
  - HTML structure changes return an empty list (PARSE_EMPTY).
  - Missing next-page control => page-0-only, logged as a warning.
"""
from __future__ import annotations

import logging
from urllib.parse import urljoin

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

PLAYWRIGHT_TIMEOUT = 60_000     # ms, page-load / selector-wait budget
PLAYWRIGHT_SETTLE_MS = 2_000    # ms, extra settle time for late XHRs
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
MAX_RESULTS = 150  # safety cap on total postings returned
MAX_PAGES = 10     # safety cap; ~20 postings/page => 200 max scanned

# The card each posting lives in. ECL = Europa Component Library, the EU
# Commission's design system; these class names are stable across Drupal
# updates. Waiting on this also confirms results have rendered.
CARD_SELECTOR = "article.ecl-content-item"

# Candidate selectors for the "next page" pagination control, tried in
# order. ECL pagination is an <nav> of <a class="ecl-pagination__link">;
# the "next" link is usually marked with rel="next" or an aria-label.
# We keep several fallbacks so a small markup tweak degrades to
# page-0-only rather than breaking. The log records which one matched.
NEXT_SELECTORS = [
    "a.ecl-pagination__link[rel='next']",
    "nav.ecl-pagination a[rel='next']",
    "a.ecl-pagination__link[aria-label*='Next' i]",
    "a.ecl-pagination__link[aria-label*='next' i]",
    "li.ecl-pagination__item--next a",
    "a[rel='next']",
]


class EuraxessScout(Scout):
    name = "euraxess"

    def fetch(self) -> list[Posting]:
        all_postings: list[Posting] = []
        seen_urls: set[str] = set()

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise RuntimeError(
                "Playwright not installed. Add 'playwright' to requirements.txt "
                "and run `playwright install chromium` (the GitHub Actions "
                "workflow does this automatically)."
            ) from e

        logger.info("Euraxess: launching Playwright for %s", SEARCH_URL[:80] + "...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(user_agent=USER_AGENT)
                page = ctx.new_page()

                # ---- Page 0 load is the fatal-if-it-fails step ----
                resp = page.goto(
                    SEARCH_URL,
                    timeout=PLAYWRIGHT_TIMEOUT,
                    wait_until="domcontentloaded",
                )
                if resp is None:
                    raise RuntimeError("Euraxess: no response object from page.goto")
                if resp.status >= 400:
                    raise RuntimeError(f"Euraxess: HTTP {resp.status} from search URL")

                # Wait for the first batch of cards to render. If this never
                # appears the page genuinely has no results (or markup
                # changed) -- treat as PARSE_EMPTY, not a crash.
                try:
                    page.wait_for_selector(CARD_SELECTOR, timeout=PLAYWRIGHT_TIMEOUT)
                except Exception:
                    logger.warning(
                        "Euraxess: no %s on page 0 -- 0 results or markup changed",
                        CARD_SELECTOR,
                    )
                    return []

                page.wait_for_timeout(PLAYWRIGHT_SETTLE_MS)

                # ---- Walk pages by clicking "next" ----
                for page_num in range(MAX_PAGES):
                    page_postings = self._parse(page.content())
                    new_count = 0
                    for posting in page_postings:
                        if posting.url in seen_urls:
                            continue
                        seen_urls.add(posting.url)
                        all_postings.append(posting)
                        new_count += 1

                    logger.info(
                        "Euraxess: page %d yielded %d new postings (%d on page, %d total)",
                        page_num, new_count, len(page_postings), len(all_postings),
                    )

                    if len(all_postings) >= MAX_RESULTS:
                        logger.info("Euraxess: hit MAX_RESULTS cap; stopping")
                        break

                    # If a page rendered but contributed nothing new, the
                    # click didn't advance us (or we've looped) -- stop.
                    if page_num > 0 and new_count == 0:
                        logger.info("Euraxess: page %d had no new postings; stopping", page_num)
                        break

                    if not self._go_to_next_page(page):
                        logger.info("Euraxess: no next-page control after page %d; stopping", page_num)
                        break

                return all_postings[:MAX_RESULTS]
            finally:
                browser.close()

    def _go_to_next_page(self, page) -> bool:
        """Click the ECL 'next page' control and wait for new cards.

        Returns True if we navigated to a new page, False if there's no
        next control (last page reached) or the click didn't take effect.
        """
        next_locator = None
        matched_selector = None
        for selector in NEXT_SELECTORS:
            locator = page.locator(selector).first
            try:
                if locator.count() > 0 and locator.is_visible():
                    next_locator = locator
                    matched_selector = selector
                    break
            except Exception:
                continue

        if next_locator is None:
            return False

        # Capture the first card's URL so we can detect when the page has
        # actually changed (more robust than waiting on a network event).
        try:
            first_before = page.locator(
                f"{CARD_SELECTOR} h3.ecl-content-block__title a"
            ).first.get_attribute("href")
        except Exception:
            first_before = None

        logger.info("Euraxess: clicking next-page control (%s)", matched_selector)
        try:
            next_locator.scroll_into_view_if_needed(timeout=PLAYWRIGHT_TIMEOUT)
            next_locator.click(timeout=PLAYWRIGHT_TIMEOUT)
        except Exception as e:
            logger.warning("Euraxess: next-page click failed (%s); stopping", e)
            return False

        # Wait until the first card's href differs from before -- that means
        # the result list re-rendered. Fall back to a fixed settle if the
        # predicate times out.
        try:
            page.wait_for_function(
                """(prev) => {
                    const a = document.querySelector(
                        'article.ecl-content-item h3.ecl-content-block__title a'
                    );
                    return a && a.getAttribute('href') !== prev;
                }""",
                arg=first_before,
                timeout=PLAYWRIGHT_TIMEOUT,
            )
        except Exception:
            logger.warning("Euraxess: page didn't visibly change after next-click; stopping")
            return False

        page.wait_for_timeout(PLAYWRIGHT_SETTLE_MS)
        return True

    def _parse(self, html: str) -> list[Posting]:
        """Parse Euraxess search results page.

        Each posting is wrapped in <article class="ecl-content-item"> with
        the title and detail link inside <h3 class="ecl-content-block__title">.
        Anchoring on the article element excludes the sidebar filter chips,
        which were the source of the bug where filter names like "Cultural
        anthropology" were being scraped as postings.
        """
        soup = BeautifulSoup(html, "lxml")
        postings: list[Posting] = []

        for card in soup.select(CARD_SELECTOR):
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
