# STATUS — Academic Job Scout

Living document. Read this first when starting a new Claude conversation
about this project. Update it at the end of each working session.

**Last updated**: 2026-06-04 (end of session #4)

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

**Important operating model (new in session #4):** Euraxess depth only
works from a residential IP, so the bot now has two modes:
- **GitHub Actions (weekly cron):** runs everything, but Euraxess returns
  only the 10 freshest postings (see "Euraxess pagination" below).
- **Local run on Matthew's laptop (`python main.py`):** runs everything
  AND gets the full ~100 Euraxess postings, because his home IP paginates.
  This is the run you do when you want deep Euraxess coverage.

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
  lines at a specific location. Also: avoid one-liner `python -c "..."`
  commands — Git Bash chokes on the parentheses/quotes. Give him a
  small script file via `cat > x.py << 'EOF'` instead.
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
  (BUT see the 401/poisoning bug under "What's broken" — this guarantee
  has a hole when *all* scoring calls fail)
- ✅ `--force-rescore` flag to ignore dedup for unsticking situations
  (used in session #4 to recover from the 401 poisoning — works great)
- ✅ Playwright fetcher with `wait_for_selector` and `scroll_to_bottom`
- ✅ RSS fetcher for sites that expose XML feeds
- ✅ `test_university.py` local debug tool (cross-platform)
- ✅ **Euraxess scraper — pagination now SOLVED (session #4).** Walks all
  pages via Playwright click-through. Local runs return the full ~100
  postings across 10 pages. See "Euraxess pagination" below for the
  important Actions-vs-local caveat.
- ✅ **University of Washington** (Playwright; 5-6 postings/run)
- ✅ **CUNY Graduate Center** (Playwright; 1 posting/run; surprisingly
  passes the WAF on Actions — see below)
- ✅ **Playwright installs reliably on Actions** — fixed in session #3,
  see "Playwright cache fix" below.

---

## What's broken or unfinished

### ✅ RESOLVED in session #4: Euraxess pagination

**The fix:** the Euraxess scout (`scouts/aggregators/euraxess.py`) now
paginates by driving a real browser (Playwright) and clicking the ECL
"next page" control, instead of building `&page=N` URLs with `requests`.
Confirmed locally: walks pages 0–9, 10 postings each, 100 total, and
recovers the high-value deep postings — including the
South/Southeast Asian Political Thought tenure-track at NTU Singapore
(scored 5★ in the session-#4 local run), which was the poster child for
what page-0-only was losing.

**Why this works where session #3's attempts failed:** the problem was
never request-level (cookies / Referer / delays, all tried in session #3,
all useless). It is IP-level: Euraxess serves cloud IPs (GitHub Actions)
a results page whose pagination is inert — both `&page=N` AND clicking
"next" return page 0 again. A residential IP gets working pagination.

**The standing caveat (this is the operating model now):**
- From **Actions** (cloud IP), the click-through still can't advance —
  the Actions log shows `page didn't visibly change after next-click;
  stopping`. So Actions still gets only the 10 freshest Euraxess postings.
  This is expected and unfixable from a cloud runner without a proxy.
- From **Matthew's laptop** (residential IP), the click-through walks all
  pages and returns ~100. So **deep Euraxess scanning is a local-run
  task**, run `python main.py` on the laptop when you want it.

If you ever want full Euraxess depth automated (not just on-demand
locally), the only real lever is changing the source IP: route the
Euraxess fetch through a residential proxy (adds a paid dependency + a
GitHub secret). Deferred — the local-run model is fine for a weekly
personal tool.

### 🔴 NEW (session #4): bot poisons the dedup DB when ALL scoring fails

In session #4 the first local run had a bad `ANTHROPIC_API_KEY` (the
shell still had the literal placeholder `"sk-ant-..."`), so **every**
one of the 99 scoring calls returned 401. The bot then went ahead and
**marked all 99 postings as seen anyway**, with zero of them actually
scored. This is the same database-poisoning failure mode STATUS has
warned about, in a new disguise: the "mark seen only after scoring"
guarantee doesn't protect against scoring *failing* — a failed call
still counts as "processed."

Recovered with `python main.py --force-rescore`, which re-scored all 99
ignoring the seen-flags. But the bot should not have needed rescue.

**Fix for a future session:** if the scoring failure rate is very high
(say 100%, or above some threshold), abort the run BEFORE writing any
seen-flags rather than committing them. A total-failure run should be a
no-op against the dedup DB, not a poisoning event. Small, high-value
hardening.

### 🟡 NEW (session #4): same-day local + Actions runs collide in git

When the laptop runs on a day Actions also ran, both write the same two
files and git conflicts on `git pull`:
- `data/digests/<date>.md` — both produce the same filename.
- `data/seen.sqlite` — single fixed-name **binary** file; produces an
  ugly binary merge conflict (hit this in session #4; resolved by
  aborting the rebase, doing a plain `git merge origin/main`, and taking
  `--ours` on both files since the local full-depth run is the keeper).

**Fix plan for session #5 (needs `core/digest.py` and `main.py` attached):**
1. **Digests:** add the run TIME to the digest filename, not just the
   date (Matthew's idea) — e.g. `2026-06-18_1407.md`. Two runs on one day
   then get distinct names and never conflict. Trade-off: you get two
   digest files on local-run weeks instead of one canonical per-date file.
2. **seen.sqlite:** the timestamp rename does NOTHING for the DB — it's
   the file that actually blocks the push. Cleanest fix: add
   `data/seen.sqlite` to `.gitignore` so local runs read/update it but
   never stage it. Risk: local and Actions dedup state drift apart, which
   mostly just means occasional repeat postings, not lost ones —
   acceptable, since the local run is the one doing the deep scan anyway.

Do BOTH and the same-day collision disappears on both files.

### NUS & NTU only see page 1 of results

Neither scraper paginates. NUS RSS feed exposes 10 postings (a fixed
window — RSS feeds are not designed for pagination); NTU Workday shows
~20 of 856 jobs across 43 pages.

Both are currently page-1-only and that's expected behavior. Now that the
Euraxess pagination story is resolved, the Playwright click-through
pattern in `scouts/aggregators/euraxess.py` is the template to copy for
NTU (it's a full SPA). NUS is RSS, so the lever there is a larger RSS
limit param or scraping the HTML portal via Playwright instead.

Note: NUS and NTU's source-health shows ⚠️ "fetched ok but parsed 0
postings" — misleading. They fetch fine; `must_match` filters out all
postings because page 1 of each happens to be STEM-heavy. Worth a small
digest polish: distinguish "0 raw postings" (selectors broken) from
"0 postings after filter" (just nothing relevant this week).

### CUNY: better than expected

STATUS predicted CUNY would 403 on Actions because of WAF blocking of
cloud IPs. As of session #4 it's still consistently returning 1 posting
per run on Actions. Either CUNY relaxed the WAF or Playwright with a real
Chromium binary slips through. Don't celebrate too hard — could revert.
Keep an eye on source-health.

### Euraxess scraper drops institution and location

`_extract_metadata` still uses the old card layout and returns
`(unknown)` and `None` for most cards. The LLM scores fine on title
alone (session-#4 digest had accurate, well-reasoned scores), but
populating institution/location would sharpen relevance scoring.
Small fix; defer.

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

## What we learned in session #4 (so we don't repeat ourselves)

- **Euraxess pagination is IP-gated, full stop.** Cloud IPs (Actions)
  get inert pagination by BOTH `&page=N` and browser click-through;
  residential IPs get working pagination by either. No request-level
  trick (cookies, Referer, delays, real browser) changes this. The only
  fix from a cloud runner would be a residential proxy. Hence the
  local-run model. Don't re-litigate this from the Actions side.
- **The clue that cracked it:** `x-deny-reason: host_not_allowed` is the
  *sandbox's own egress proxy* talking, not Euraxess. A Claude container
  can't reach euraxess.ec.europa.eu at all, so it can't reproduce the
  Actions environment for this site — all live testing must happen on
  Matthew's laptop or in an actual Actions run.
- **Windows local runs need `tzdata`.** `main.py` does
  `ZoneInfo("Europe/Zurich")`; Linux (Actions) reads tz data from the OS,
  but Windows has no system tz database and crashes with
  `ZoneInfoNotFoundError` until you `python -m pip install tzdata`.
  **TODO:** add `tzdata` to `requirements.txt` so it's documented.
- **`ANTHROPIC_API_KEY` is per-terminal locally.** `export` only lasts
  the session; close Git Bash and the next run 401s. Add it to
  `~/.bashrc` for persistence. (And see the DB-poisoning bug above — a
  bad key is how we found it.)
- **Binary merge conflicts on `seen.sqlite` are painful.** When a rebase
  tangles on it, `git rebase --abort`, then `git merge origin/main`, then
  `git checkout --ours <files>` + `git add` + `git commit --no-edit`.
  Note `--ours` means the current branch in a *merge* (the keeper) but
  the opposite in a *rebase* — prefer merge here to avoid confusion.
- **Don't leave junk in the repo.** Session #4 found a stale untracked
  `scouts/euraxess.py` (the OLD pre-session-3 scout — the REAL one is at
  `scouts/aggregators/euraxess.py`) and an Office lock file
  `data/digests/~$...md`. The stale `scouts/euraxess.py` is not tracked
  by git and should be deleted to avoid confusing future debugging.

---

## What we learned in session #3 (kept for reference)

- **Playwright cache invalidation**: include the **installed Playwright
  version** in the Actions cache key (read via `pip show playwright`, not
  `playwright.__version__`). Otherwise the cached Chromium goes stale when
  Playwright upgrades. See `.github/workflows/weekly-scan.yml`.
- **Euraxess URL filtering works** from a residential IP via plain
  `requests.get`, no session state — the 47-filter saved-search URL
  returns "Search results (114)". (Pagination is the part that's IP-gated;
  the filtering is not.)
- **Don't anchor on `a[href^='/jobs/']`** in Euraxess — the sidebar filter
  chips are also `/jobs/...` anchors and get scraped as fake postings.
  Anchor on `article.ecl-content-item` (the ECL design-system card class).

---

## Carryover lessons from earlier sessions

- **For Python newbies, "paste the whole file" beats "insert these
  lines."** Em-dashes, smart quotes, and indentation issues are very hard
  to debug remotely; whole-file replacements with Ctrl+A → paste → save
  are far more reliable. Default to this. When copy-paste corrupts (e.g.
  bracketed-paste `[[200~` junk, or chat text leaking into the file),
  prefer dropping the file in via `cp ~/Downloads/x.py <dest>`.
- **Workday's `data-automation-id` attributes are the stable selectors.**
  Don't use auto-generated `css-1q2dra3`-style class names.
- **Playwright with a residential IP got through CUNY's WAF.** Plain
  `requests` is hopeless. (Also works on Actions IPs as of session #3,
  but trust this fragilely.)
- **Workflow runs push commits back.** If you commit locally and try to
  push, you may get "rejected (fetch first)". Run `git pull`, resolve the
  merge prompt with `:wq` in Vim if it opens, then `git push` again. (See
  the session-#4 same-day-collision note for the binary-conflict variant.)
