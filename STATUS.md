# STATUS — Academic Job Scout

Living document. Read this first when starting a new Claude conversation
about this project. Update it at the end of each working session.

**Last updated**: 2026-05-14 (end of session #2)

---

## What this project is

A weekly job-scanning bot for **Jasnea Sarma**, a political geographer at
the University of Zurich looking for tenure-track or equivalent permanent
academic positions. Hits academic job aggregators and configured university
career pages, deduplicates against past runs, sends each new posting through
Claude (Haiku) for relevance scoring against `profile/jasnea.md`, and emails
a digest of the best matches.

Runs every Monday via GitHub Actions. Mailer is currently stubbed —
digests are committed to `data/digests/` instead of being sent.

Repo: https://github.com/Mgreinert/AcademicJobScout
Local path on Matthew's Windows machine:
`C:\Users\Thesq\Documents\Jasnea\academic job scout\academic-job-scout`

---

## Who's who

- **Matthew Greinert** (Mgreinert / Thesq on Windows) — owner of the repo,
  writes Git commits, drives the project. Comfortable with `add/commit/push`
  basics; still a Python newbie, needs explicit step-by-step instructions
  for code changes (indentation level, where in a file something goes, etc).
  Tip for future Claudes: when asking him to edit a Python file, default to
  giving him the **whole file** to paste in place rather than asking him to
  insert lines at a specific location.
- **Jasnea Sarma** — the researcher this bot serves. Her CV is the basis
  of `profile/jasnea.md`. She's not the one running the bot.

---

## Architecture (one-paragraph version)

`main.py` is the orchestrator. It loads scouts (one Euraxess aggregator
plus N university scouts driven by `config/universities.yaml`), fetches
postings from each, tracks per-source health in SQLite, deduplicates
against `data/seen.sqlite`, scores survivors with Claude Haiku via
`core/relevance.py`, builds a markdown digest with `core/digest.py`,
and stub-mails it via `core/mailer.py`. Dedup state and digests are
committed back to the repo by the GitHub Actions workflow each run.

See `README.md` for the full layout and `core/digest.py` for the exact
digest format (with the timestamp header and "What the scrapers saw"
diagnostic section).

---

## What's working

- ✅ End-to-end pipeline: scout → dedup → LLM score → digest → stub email
- ✅ GitHub Actions weekly cron (`.github/workflows/weekly-scan.yml`)
- ✅ Manual workflow trigger with optional `--force-rescore` checkbox
- ✅ Per-source health reporting (FETCH_FAILED / PARSE_EMPTY / OK +
  zero-results streak detection)
- ✅ Diagnostic "What the scrapers saw" section in digest, showing every
  posting + its fate (kept / scored-low / seen-before)
- ✅ Timestamps in digest (Zurich local + UTC + run duration)
- ✅ Dedup DB only marks postings "seen" *after* the LLM scores them
  (prevents "poisoned DB" from a half-broken run)
- ✅ `--force-rescore` flag to ignore dedup for unsticking situations
- ✅ Playwright fetcher with `wait_for_selector` and `scroll_to_bottom`
  knobs for JS-rendered sites
- ✅ **RSS fetcher** (new in session #2) for sites that expose XML feeds —
  far more reliable than HTML scraping. See `_parse_rss` in
  `scouts/universities.py`.
- ✅ `test_university.py` local debug tool, now cross-platform (uses
  `tempfile.gettempdir()` instead of hardcoded `/tmp/`)
- ✅ **Euraxess scraper** — finds ~20 postings/run. LLM correctly drops
  all the STEM/medical postings as 1★. Signal-to-noise is low but expected.
- ✅ **All four university scrapers now working** (as of session #2):
  - University of Washington (Playwright; 6 postings/run)
  - Nanyang Technological University (Playwright + scroll; ~20/page)
  - National University of Singapore (RSS feed; ~10/run after must_match)
  - CUNY Graduate Center (Playwright; works locally, see caveat below)

---

## What's broken or unfinished

### CUNY will probably 403 on GitHub Actions

CUNY's WAF blocks cloud IPs (Azure, AWS). The scraper works perfectly
from Matthew's home machine via Playwright, but when the bot runs on
GitHub Actions, it's expected to fail with 403. We're deferring this:
the source-health system will show `FETCH_FAILED` weekly, which is
honest reporting. Three eventual fixes to choose from later:

1. Find a CUNY RSS feed (gc.cuny.edu is Drupal-based; many such sites
   expose one). Worth a check.
2. Wait until an Interfolio aggregator scout is built — it would
   resyndicate CUNY postings via a different (non-blocked) host.
3. Accept the failure and let Matthew check CUNY manually.

### Euraxess limitations (unchanged from session #1)

- Only fetches the default search page (~20 postings, all fields).
- LLM correctly drops everything irrelevant but most weeks Euraxess
  produces zero kept matches — current postings are STEM-heavy.
- See "Next steps" below for the planned improvement.

### Mailer (unchanged from session #1)

- Still stubbed (writes to `data/digests/<date>.md`).
- Decision pending on Resend vs Gmail SMTP, plus recipient address.
- Defer until aggregators are in and there's reliably good content to send.

### Aggregators not yet built (unchanged priority list)

1. **H-Net Job Guide** — strong for humanities/social sciences.
2. **jobs.ac.uk** — UK and Commonwealth, with category filters.
3. **AAG Jobs Center** — Association of American Geographers.
4. **Interfolio search** — would cover UW, CUNY, and many other US
   universities that route faculty hires through Interfolio.
5. **Academic Jobs Online (AJO)**, **HigherEdJobs**, **AAS Job Board**,
   **RGS-IBG** — later.

---

## What we learned in session #2 (so we don't repeat ourselves)

- **NUS exposes an RSS feed** at
  `https://careers.nus.edu.sg/services/rss/category/?catid=545744`
  (linked from the HTML page itself). RSS was much simpler and more
  reliable than the JS-rendered portal. Worth checking for RSS first
  on any SuccessFactors / SAP-based career site before reaching for
  Playwright.
- **Workday's `data-automation-id` attributes are the stable selectors.**
  Auto-generated `css-1q2dra3`-style class names will change between
  deploys and shouldn't be used. Also: NTU's `wait_for_selector` on an
  individual title link timed out because of visibility issues — waiting
  on the broader `jobResults` *section* (and adding `scroll_to_bottom`)
  worked.
- **UW's page structure** uses semantic `<li class="ap-job-item">` with
  child spans for title/unit/location. The previous selector
  (`a[href*='position-details']`) was matching the right anchor but
  using it as the *posting unit*, so the title text was just "More info"
  and must_match filtered everything out. Lesson: when the per-posting
  card is rich, anchor on the wrapper element, not on the anchor tag.
- **NTU is tech-heavy.** Even with a working scraper, expect most weeks
  to produce 0 keeper postings because page 1 of 43 is biomedical and
  engineering. Not a bug.
- **Playwright with a home IP got through CUNY's WAF.** Plain `requests`
  is hopeless. This is also a confirmation that the WAF distinguishes by
  IP, not by browser fingerprint.
- **For Python newbies, "paste the whole file" beats "insert these lines."**
  We hit indentation and em-dash encoding errors when trying to splice in
  a new method. The whole-file approach with explicit Ctrl+A → paste →
  save is more reliable.

---

## Carryover lessons from session #1

- **First Euraxess scout** used ke