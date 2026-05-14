# STATUS — Academic Job Scout

Living document. Read this first when starting a new Claude conversation
about this project. Update it at the end of each working session.

**Last updated**: 2026-05-14 (end of session #1)

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
  writes Git commits, drives the project. GitHub newbie; comfortable with
  Git Bash basics now but needs explicit step-by-step instructions for
  anything beyond `add/commit/push/pull`.
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

See `README.md` for the full layout and `core/digest.py` for the
exact digest format (with the timestamp header and the "What the
scrapers saw" diagnostic section).

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
  knobs for JS-rendered sites (Workday etc.)
- ✅ `test_university.py` local debug tool (Matthew has not yet used it —
  Python is installed but the script hasn't been run locally)
- ✅ **Euraxess scraper** — finds ~20 postings/run. LLM correctly drops
  all the STEM/medical postings as 1★. The signal-to-noise problem here
  is real but expected (see "Euraxess limitations" below).

---

## What's broken or unfinished

### Four university scrapers all fail in slightly different ways

As of the last run (2026-05-14):

1. **University of Washington** —
   `jobs_url: https://ap.washington.edu/ahr/academic-jobs/`
   Playwright reaches the page (no 403, good!) but parses **0 postings**.
   Current selector `a[href*='position-details']` doesn't match the
   rendered DOM. Need actual HTML to write a working selector.

2. **National University of Singapore** —
   `jobs_url: https://careers.nus.edu.sg/NUS/go/Academic-and-Research-Positions/545744/`
   Playwright times out waiting for `a.jobTitle-link, tr.data-row, .job-title`.
   The URL is probably right but the selector is wrong, or the page uses
   different markup than expected SuccessFactors.

3. **Nanyang Technological University** —
   `jobs_url: https://ntu.wd3.myworkdayjobs.com/Careers`
   Playwright reaches the page but parses **0 postings**. Workday
   `data-automation-id` attributes that should work in theory aren't
   matching. May need an additional wait, or selectors may differ in
   NTU's Workday config.

4. **CUNY Graduate Center** —
   `jobs_url: https://www.gc.cuny.edu/human-resources/employment-opportunities`
   Returns **403 Forbidden** to plain requests. The gc.cuny.edu page is
   WAF-protected from cloud IPs. Likely fix: switch to Playwright, or
   pivot to a different URL (cuny.jobs aggregator, or HigherEdJobs
   institution feed).

### Euraxess limitations

- Only fetches the default search page (~20 postings, all fields, all
  countries). Euraxess strips query parameters from search URLs, so a
  URL-based `?keywords=...` filter doesn't work.
- The LLM correctly drops everything irrelevant, but this means most
  weeks Euraxess produces zero kept matches — most recent postings are
  in STEM fields.
- See "Next: improving Euraxess" below.

### Mailer

- Still stubbed (writes to `data/digests/<date>.md`).
- Decision pending on Resend vs Gmail SMTP, plus recipient address.
- Matthew said "later" — fine to defer until the scrapers are healthier
  and there's actually something worth emailing.

### Aggregators not yet built

Planned, in order of priority:
1. **H-Net Job Guide** — strong for humanities/social sciences with
   field tags. Should map cleanly to Jasnea's profile.
2. **jobs.ac.uk** — UK and Commonwealth, with category filters.
3. **AAG Jobs Center** — Association of American Geographers,
   field-specific and directly on-target.
4. **Interfolio search** — would cover UW and many other US universities
   that route faculty hires through Interfolio (would partially obsolete
   the UW direct scraper).
5. **Academic Jobs Online (AJO)**, **HigherEdJobs**, **AAS Job Board**,
   **RGS-IBG** — later.

---

## What we've already tried (so we don't repeat ourselves)

- **First Euraxess scout** used keyword-search URLs. Didn't work because
  Euraxess strips query params. Replaced with default-search-page scrape.
- **First UW URL** was the Workday portal (`uwhires.admin.washington.edu`).
  Wrong — that's for non-academic staff. The correct page is
  `ap.washington.edu/ahr/academic-jobs/`. Plain `requests` got 403 from
  it; Playwright gets through but selectors still need tuning.
- **First NTU URL** (`ntu.edu.sg/about-us/careers/job-opportunities`) was
  404'd. NTU moved to Workday at `ntu.wd3.myworkdayjobs.com/Careers`.
- **First CUNY URL** was `cuny.jobs/jobs/?cat=faculty`. Returned 0 postings.
  Tried switching to `gc.cuny.edu/human-resources/employment-opportunities`
  but that's 403-protected.
- **First version of dedup** marked everything fetched as seen, even if
  the LLM never scored it. This caused a "poisoned DB" issue: after one
  broken run, all subsequent runs saw the same postings as "already seen"
  and skipped LLM scoring entirely. **Fixed**: dedup now only marks
  postings that were actually scored, and a `--force-rescore` flag exists
  for recovering from this kind of state.

---

## Immediate next steps (recommended order)

1. **Use `test_university.py` to inspect the actual HTML for each broken
   scraper.** Matthew now has Python 3.14 installed locally. Run from
   the project folder:

   ```
   pip install -r requirements.txt
   python -m playwright install chromium
   python test_university.py "Washington" --raw
   ```

   This dumps the page HTML to `/tmp/University_of_Washington.html`.
   Open it, paste relevant chunks (the structure of one job posting) to
   the next Claude, and get exact selectors.

   Repeat for NUS, NTU, CUNY.

2. **Once the four universities work**, build the H-Net scout. H-Net's job
   guide has stable HTML with field-tag filters, and is the highest-value
   addition for Jasnea's field.

3. **Then jobs.ac.uk and AAG.** These are also field-friendly.

4. **Then consider improving Euraxess** by either (a) using Playwright to
   submit the Research Field filter, or (b) reverse-engineering the
   internal search API by inspecting network calls in a browser.

5. **Once the digest reliably finds good matches, wire up real email**
   (Resend or Gmail SMTP). Profile and recipient need to be confirmed.

---

## How a new chat should start

Recommended opening message for a new conversation:

> *I'm continuing work on an academic job scanner for my wife. Read
> `STATUS.md` first, then `README.md`, then skim `config/universities.yaml`
> and `main.py`. Today I want to [whatever the goal is].*

Attach (or paste) the contents of those files. Claude can't browse the
GitHub repo — files have to be in the conversation context.

If working on a specific broken scraper, also attach a real DOM snippet
(captured via `python test_university.py "<name>" --raw`).

---

## Conventions worth keeping

- **Always end a session by updating this STATUS.md** with what changed,
  what's working/broken now, and what to do next.
- **Local edits → `git pull --rebase` → commit → push.** The bot runs on
  GitHub and commits back, so local always lags. Pulling first avoids
  the "fetch first" rejection.
- **Selector changes go in `config/universities.yaml`**, not in code,
  unless a structural change is needed.
- **Aggregator scouts are one Python file each** in `scouts/aggregators/`.
  Each implements `Scout.fetch() -> list[Posting]`. Use
  `scouts/aggregators/euraxess.py` as a template.
- **When a scraper breaks**, don't guess at selectors — dump the real HTML
  with `test_university.py --raw` and write selectors against the actual
  DOM.

---

## Open questions for Matthew

- Final email recipient: Matthew, Jasnea, or both?
- Email provider preference: Resend (clean, needs a domain) or Gmail SMTP
  (no domain, uses app password)?
- Once university scrapers work, are there other universities to add now,
  or should we wait until aggregators are also in?
