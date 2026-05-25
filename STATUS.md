# STATUS — Academic Job Scout

Living document. Read this first when starting a new Claude conversation
about this project. Update it at the end of each working session.

**Last updated**: 2026-05-25 (end of session #3)

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
  writes Git commits, drives the project. Uses **Git Bash** for git
  commands and **Notepad** for editing files. Comfortable with
  `add/commit/push` basics; still a Python newbie, needs explicit
  step-by-step instructions for code changes. Tip for future Claudes:
  when asking him to edit a Python file, default to giving him the
  **whole file** to paste in place rather than asking him to insert
  lines at a specific location.
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
- ✅ Diagnostic "What the scrapers saw" section in digest
- ✅ Timestamps in digest (Zurich local + UTC + run duration)
- ✅ Dedup DB only marks postings "seen" *after* the LLM scores them
- ✅ `--force-rescore` flag to ignore dedup for unsticking situations
- ✅ Playwright fetcher with `wait_for_selector` and `scroll_to_bottom`
- ✅ RSS fetcher for sites that expose XML feeds
- ✅ `test_university.py` local debug tool (cross-platform)
- ✅ **Euraxess scraper** — uses a 47-filter saved-search URL covering
  Jasnea's fields. Local runs return ~100 highly relevant postings.
  See "Euraxess pagination on Actions" below for a serious caveat.
- ✅ **University of Washington** (Playwright; 5-6 postings/run)
- ✅ **CUNY Graduate Center** (Playwright; 1 posting/run; surprisingly
  passes the WAF on Actions — see below)
- ✅ **Playwright now installs reliably on Actions** — fixed in session
  #3, see "Playwright cache fix" below.

---

## What's broken or unfinished

### 🔴 Euraxess pagination silently fails on Actions (NEW, session #3)

The Euraxess scraper paginates correctly on Matthew's laptop (returns
~100 postings across multiple pages) but on GitHub Actions, page 1
returns the **same 10 postings as page 0** — they're never new, so
our dedup-and-stop logic gives up after page 1.

What we tried in session #3 (none of which helped):
1. `requests.Session()` to persist cookies across page fetches.
2. 2-second sleep between pages.
3. `Referer` header pointing at the previous page.

The Actions log confirms: page 0 yields 10 new postings; page 1 returns
10 postings on the page, 0 of which are new (i.e. literally the same
10 items). This means Euraxess is either:
- IP-rate-limiting / caching responses for the GitHub Actions IP range
- Stripping the `&page=N` parameter for our requests
- Or some CDN/proxy in between is doing it

Net effect right now: we get only the top 10 Euraxess postings each
week instead of the top ~100. Because the URL sorts by `created DESC`,
those 10 are at least the freshest, but high-value postings that aren't
in the top 10 (like the South/Southeast Asian Political Thought
tenure-track at https://euraxess.ec.europa.eu/jobs/438366) get missed
entirely.

**Options for next session, in rough order of effort:**

1. **Look for a Euraxess RSS or JSON feed.** Some Drupal sites
   expose `/rss.xml` or `/jsonapi/` endpoints alongside their HTML
   pages. If one exists with the filter URL parameters honored,
   this is a clean win (10 minutes to test). Open
   https://euraxess.ec.europa.eu/rss.xml in a browser to start.
2. **Switch the Euraxess scout to Playwright.** Drive a real browser
   through the pagination UI. Almost certainly works but adds ~60s
   per weekly run.
3. **Accept page-0-only.** Just lower MAX_PAGES to 1 and live with
   10 freshest postings/week. The bot keeps working; we just miss
   some long-tail content. Acceptable as a long-term resting state
   if 1 and 2 don't pan out.

### NUS & NTU only see page 1 of results

Neither scraper paginates. NUS RSS feed exposes 10 postings (a fixed
window — RSS feeds are not designed for pagination); NTU Workday shows
~20 of 856 jobs across 43 pages.

Both are currently page-1-only and that's expected behavior. Worth
revisiting once the Euraxess pagination story is resolved, since the
same techniques will likely apply:
- NUS: try a larger RSS limit parameter or scrape the HTML portal
  via Playwright as an alternative.
- NTU: Playwright would need to click through pagination — biggest
  lift of the three since it's a full SPA.

Note: NUS and NTU's source-health currently shows ⚠️ "fetched ok but
parsed 0 postings" — which is misleading. They're actually fetching
fine; `must_match` is just filtering out all postings because page 1
of each happens to be STEM-heavy. Worth a small polish to the digest:
distinguish "0 raw postings" (selectors broken) from "0 postings after
filter" (just nothing relevant this week).

### CUNY: better than expected

STATUS predicted CUNY would 403 on Actions because of WAF blocking of
cloud IPs. As of session #3, CUNY is consistently returning 1 posting
per run on Actions. Either CUNY relaxed the WAF or Playwright with a
real Chromium binary slips through. Don't celebrate too hard — could
revert. Keep an eye on source-health.

### Euraxess scraper drops institution and location

The new ECL-based card structure (session #3) confirmed the parser
finds title + URL correctly, but `_extract_metadata` still uses the
old card layout and returns `(unknown)` and `None`. LLM doesn't
strictly need these (title is informative on its own) but it would
improve relevance scoring. Small fix; defer to next session.

### Mailer (unchanged from earlier)

- Still stubbed (writes to `data/digests/<date>.md`).
- Decision pending on Resend vs Gmail SMTP, plus recipient address.
- Defer until aggregators are in and there's reliably good content
  to send.

---

### Aggregators not yet built (unchanged priority list)

1. **H-Net Job Guide** — strong for humanities/social sciences.
2. **jobs.ac.uk** — UK and Commonwealth, with category filters.
3. **AAG Jobs Center** — Association of American Geographers.
4. **Interfolio search** — would cover UW, CUNY, and many other US
   universities that route faculty hires through Interfolio.
5. **Academic Jobs Online (AJO)**, **HigherEdJobs**, **AAS Job Board**,
   **RGS-IBG** — later.

---

## What we learned in session #3 (so we don't repeat ourselves)

- **Playwright cache invalidation**: Playwright frequently bumps its
  bundled Chromium revision. If your Actions workflow caches the
  Playwright browsers folder with a key that only depends on
  `requirements.txt`, the cache silently goes stale when Playwright
  upgrades, and the cached binary won't match what the new
  Playwright wants. The fix: include the **installed Playwright
  version** in the cache key. Read it via `pip show playwright`,
  not `playwright.__version__` (which doesn't exist on the
  top-level module). See `.github/workflows/weekly-scan.yml` for
  the working version.
- **Euraxess URL filtering works**: the 47-filter saved-search URL
  loads correctly via `requests.get` from a residential IP, no
  session state needed. Confirmed by hitting it directly and seeing
  "Search results (114)" in the response. Filters that work via URL
  alone are rare on Drupal-based sites — Euraxess is friendly here.
- **Euraxess `&page=N` does NOT work from GitHub Actions IPs**, even
  though it works fine from residential IPs. Cookies, Referer
  headers, and inter-page delays don't help. This is IP-level
  behavior, not request-level.
- **Don't anchor on `a[href^='/jobs/']`** in Euraxess. The sidebar
  filter chips on the filtered-search page are also `/jobs/...`
  anchors and get scraped as fake postings (like "Cultural
  anthropology"). Anchor on `article.ecl-content-item` instead,
  which is the EU Commission's ECL design-system class for each
  actual posting card.
- **For NUS/NTU**, "selectors may be broken" warnings in source-health
  can be false alarms. The selectors work, the parser fetches a
  full page of postings, but `must_match` filters them all out
  because there's just no Jasnea-relevant content that week. The
  warning UX could distinguish these cases.

---

## Carryover lessons from earlier sessions

- **For Python newbies, "paste the whole file" beats "insert these
  lines."** Em-dashes, smart quotes, and indentation issues are very
  hard to debug remotely; whole-file replacements with Ctrl+A → paste
  → save are far more reliable. Default to this.
- **Workday's `data-automation-id` attributes are the stable selectors.**
  Don't use auto-generated `css-1q2dra3`-style class names.
- **Playwright with a residential IP got through CUNY's WAF.** Plain
  `requests` is hopeless. (Update: also works on Actions IPs as of
  session #3, but trust this fragilely.)
- **Workflow runs push commits back.** If you commit locally and try
  to push, you may get "rejected (fetch first)". Run `git pull`,
  resolve the merge prompt with `:wq` in Vim if it opens, then `git
  push` again. Will not overwrite your local changes — git is smart
  about merging commits that touch different files.