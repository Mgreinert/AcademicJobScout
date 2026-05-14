# Academic Job Scout

A weekly job-scanning bot that searches academic job aggregators and
university career pages, filters postings against a researcher's profile
using Claude, and sends an email digest of the best matches.

Built for Jasnea Sarma (political geography, border studies, Asia studies)
but the profile is swappable — see `profile/jasnea.md`.

## How it works

```
                    Weekly cron (Mon UTC) — GitHub Actions
                                  │
                                  ▼
                         scouts (parallel-ish):
                         · aggregators (Euraxess, …)
                         · universities (YAML-driven)
                                  │
                                  ▼
                       SQLite dedup (drop seen)
                                  │
                                  ▼
                  Claude relevance scoring (1–5)
                                  │
                                  ▼
                  Markdown digest + source-health footer
                                  │
                                  ▼
                      Email (stubbed for now)
```

## Quick start

```bash
git clone <your-repo>
cd academic-job-scout

# 1. Local dependencies
pip install -r requirements.txt
python -m playwright install chromium    # only needed if a scout uses playwright

# 2. API key
export ANTHROPIC_API_KEY=...

# 3. Run once locally
python main.py
# → writes digest to data/digests/<today>.md (stub mailer)

# 4. Tune a university's selectors before pushing
python test_university.py "Washington"             # quick check
python test_university.py "Washington" --raw       # also dump HTML to /tmp/
```

To deploy: push to GitHub, add `ANTHROPIC_API_KEY` as a repo secret in
Settings → Secrets and variables → Actions, and either wait for Monday or
trigger the workflow manually from the Actions tab.

## Directory layout

```
academic-job-scout/
├── .github/workflows/weekly-scan.yml   # cron trigger
├── scouts/
│   ├── aggregators/                    # one file per aggregator
│   │   └── euraxess.py
│   └── universities.py                 # generic; reads config/universities.yaml
├── config/
│   └── universities.yaml               # user-editable list of universities
├── core/
│   ├── models.py                       # Posting dataclass
│   ├── dedup.py                        # SQLite "already shown" store
│   ├── health.py                       # per-source success/failure tracking
│   ├── relevance.py                    # Claude relevance scoring
│   ├── digest.py                       # markdown digest builder
│   └── mailer.py                       # email (stubbed)
├── profile/
│   └── jasnea.md                       # researcher profile, fed to Claude
├── data/
│   ├── seen.sqlite                     # dedup + health DB (committed)
│   └── digests/                        # past digests (stub-mailer output)
├── main.py                             # orchestrator
├── test_university.py                  # debug single-university config
└── requirements.txt
```

## Adding a university

Edit `config/universities.yaml`:

```yaml
- name: University of X
  jobs_url: https://x.edu/careers/faculty
  posting_selector: ".job-listing"
  title_selector: ".job-title"
  link_selector: "a"
  must_match: ["geography", "asia"]
  fetcher: requests             # or playwright
  # Playwright-only knobs:
  wait_for_selector: "[data-automation-id='jobTitle']"   # for Workday
  scroll_to_bottom: false
```

Then test locally before pushing:

```bash
python test_university.py "X" --raw
```

`--raw` dumps the actual HTML the scraper sees to `/tmp/`, which is
invaluable for figuring out the right CSS selectors when the first guess
doesn't match.

## Source health

Every digest ends with a status block per source. Three failure modes
are distinguished:

- ❌ **fetch failed** — network or auth error (often 403 from a WAF)
- ⚠️ **fetched but parsed nothing** — HTML likely changed, selectors broken
- ⚠️ **consistently zero results** — clean runs but 0 postings for ≥3 weeks

## Reality check: WAFs and cloud IPs

Many university job boards (notably UW) sit behind WAFs that block
requests from cloud IP ranges — Microsoft Azure (where GitHub Actions
runs), AWS, GCP — regardless of User-Agent. Plain `requests` will 403,
and Playwright with a real browser will also 403 because the block is
on the IP, not the browser fingerprint.

When you see persistent 403s for a university:

1. **Try an aggregator that re-syndicates that institution.** Interfolio
   (`apply.interfolio.com`) is used by hundreds of US universities,
   including UW; H-Net Job Guide and HigherEdJobs also cross-list. Often
   the easiest fix is to drop the direct-scrape entry and rely on the
   aggregator instead.
2. **Look for an official RSS/JSON feed.** Many career portals expose one
   that isn't WAF-protected.
3. **Run from a residential IP.** If you have a home server or a friend's
   machine, that bypasses the cloud-IP block. Trade-off: more setup,
   reliability depends on the machine being up.

The Playwright code path is still valuable for sites that are simply
JavaScript-rendered (single-page apps, Workday for institutions that
don't IP-block, modern career portals) — IP-blocked sites are the
exception, not the rule.

## Email setup (when you're ready)

The mailer is currently a stub — it writes the digest to
`data/digests/<date>.md` instead of sending. To switch on real email:

**Option A: Resend** (simplest)

1. Sign up at resend.com (free tier: 100 emails/day).
2. Add a verified sender domain.
3. In GitHub repo Settings → Secrets, add `RESEND_API_KEY`,
   `DIGEST_FROM`, `DIGEST_RECIPIENT`.
4. In Settings → Variables, add `MAILER=resend`.
5. Edit `core/mailer.py` and uncomment the resend block in `_send_resend`.

**Option B: Gmail SMTP**

1. Generate a Google "app password" at account.google.com/apppasswords.
2. Add `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `DIGEST_RECIPIENT` as secrets.
3. Add `MAILER=gmail` as a variable.
4. Uncomment the SMTP block in `_send_gmail`.
