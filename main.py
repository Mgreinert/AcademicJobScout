"""
Academic Job Scout — main orchestrator.

Run every Monday by GitHub Actions; can also be run locally:

    export ANTHROPIC_API_KEY=...
    python main.py                  # normal run
    python main.py --force-rescore  # ignore dedup; re-score everything

Pipeline:
  1. Instantiate scouts: every aggregator + every university from YAML.
  2. Fetch each (wrapped in try/except so one bad source can't kill the run).
  3. Record per-source health (ok / fetch_failed / parse_empty / zero_streak).
  4. Track each posting's "fate" so the digest can show what the scraper saw,
     independently of dedup and LLM filtering.
  5. Deduplicate against the SQLite store (unless --force-rescore).
  6. Score new postings with Claude (Haiku).
  7. Drop low-scoring ones, build a markdown digest grouped by score,
     with a "What the scrapers saw" debug section and source-health footer.
  8. Send (currently stubbed to disk).
  9. Persist new postings as "seen" — only the ones we actually scored,
     so a run that errors out before LLM scoring doesn't poison the DB.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Make sibling packages importable when run as `python main.py`
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.dedup import DedupStore
from core.digest import PostingTrace, build_digest
from core.health import HealthStore, RunStatus
from core.mailer import send_digest
from core.models import Posting
from core.relevance import MIN_SCORE_TO_INCLUDE, score_postings

from scouts import Scout
from scouts.aggregators.euraxess import EuraxessScout
from scouts.universities import load_university_scouts


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger("scout")


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "seen.sqlite"
PROFILE_PATH = ROOT / "profile" / "jasnea.md"
UNIVERSITIES_CONFIG = ROOT / "config" / "universities.yaml"

# Zurich time for human-readable timestamps in the digest.
LOCAL_TZ = ZoneInfo("Europe/Zurich")


def gather_scouts() -> list[Scout]:
    """Build the full scout list: aggregators + universities from YAML."""
    aggregators: list[Scout] = [
        EuraxessScout(),
        # Add more aggregator scouts here as we build them:
        # HNetScout(), JobsAcUkScout(), AAGScout(), AJOScout(),
        # InsideHigherEdScout(), AASScout(), HigherEdJobsScout(),
    ]
    universities: list[Scout] = load_university_scouts(UNIVERSITIES_CONFIG)
    return aggregators + universities


def run_scout(scout: Scout, health: HealthStore):
    """Run a single scout, record health, return (postings, report)."""
    try:
        postings = scout.fetch()
    except Exception as e:
        logger.exception("Scout %s failed", scout.name)
        report = health.record_run(scout.name, RunStatus.FETCH_FAILED, 0, str(e))
        return [], report

    if not postings:
        report = health.record_run(scout.name, RunStatus.PARSE_EMPTY, 0)
    else:
        report = health.record_run(scout.name, RunStatus.OK, len(postings))
    return postings, report


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Academic Job Scout")
    p.add_argument(
        "--force-rescore",
        action="store_true",
        help="Ignore the dedup database for this run. Every fetched posting "
             "is scored by the LLM, regardless of whether it was seen before. "
             "Useful for recovering from a poisoned dedup DB (e.g. when an "
             "earlier broken run marked postings as 'seen' without scoring "
             "them). Costs more API credits.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    started_utc = datetime.now(timezone.utc)
    started_local = started_utc.astimezone(LOCAL_TZ)
    logger.info("=== Academic Job Scout starting at %s (Zurich %s) ===",
                started_utc.isoformat(timespec="seconds"),
                started_local.isoformat(timespec="seconds"))
    if args.force_rescore:
        logger.warning("--force-rescore: dedup DB ignored for this run")

    dedup = DedupStore(DB_PATH)
    health = HealthStore(DB_PATH)

    scouts = gather_scouts()
    logger.info("Loaded %d scouts: %s", len(scouts), [s.name for s in scouts])

    # Phase 1: fetch from every scout, collect every posting + report
    all_postings: list[Posting] = []
    reports = []
    for scout in scouts:
        logger.info("→ Running %s", scout.name)
        postings, report = run_scout(scout, health)
        logger.info("   %s → %d postings, status=%s",
                    scout.name, len(postings), report.status.value)
        all_postings.extend(postings)
        reports.append(report)

    # Phase 2: build a per-posting trace so we can show "what the scrapers saw"
    # in the digest. Each posting goes through dedup → (maybe) LLM → keep/drop.
    traces: dict[str, PostingTrace] = {}
    for p in all_postings:
        traces[p.uid] = PostingTrace(posting=p, fate="seen-before")

    # Phase 3: dedup (or skip dedup if --force-rescore)
    if args.force_rescore:
        candidates = list(all_postings)
    else:
        candidates = dedup.filter_new(all_postings)
    for p in candidates:
        traces[p.uid].fate = "to-score"
    logger.info("Fetched: %d total, candidates for scoring: %d",
                len(all_postings), len(candidates))

    # Phase 4: score with Claude
    scored: list[Posting] = []
    if candidates:
        if not PROFILE_PATH.exists():
            logger.warning(
                "No profile at %s — relevance filter will be poor. "
                "Add a real CV/profile.", PROFILE_PATH,
            )
            PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
            PROFILE_PATH.write_text(
                "Academic researcher, field unspecified.", encoding="utf-8"
            )
        # score_postings returns only those at/above MIN_SCORE_TO_INCLUDE,
        # but it mutates fit_score/fit_rationale on ALL inputs, so we
        # iterate over the original `candidates` to populate every trace.
        scored = score_postings(candidates, PROFILE_PATH)
        kept_uids = {p.uid for p in scored}
        for p in candidates:
            t = traces[p.uid]
            if p.uid in kept_uids:
                t.fate = "kept"
            else:
                t.fate = "scored-low"
            t.fit_score = p.fit_score
            t.fit_rationale = p.fit_rationale
        logger.info("Kept %d of %d after relevance filter (score >= %d)",
                    len(scored), len(candidates), MIN_SCORE_TO_INCLUDE)

    # Phase 5: build digest with timestamps + the per-posting visibility trace
    finished_utc = datetime.now(timezone.utc)
    finished_local = finished_utc.astimezone(LOCAL_TZ)
    subject, body = build_digest(
        kept_postings=scored,
        traces=list(traces.values()),
        source_reports=reports,
        started_utc=started_utc,
        finished_utc=finished_utc,
        started_local=started_local,
        finished_local=finished_local,
    )
    status = send_digest(subject, body)
    logger.info("Mailer: %s", status)

    # Phase 6: mark as seen ONLY postings that were actually scored. If a
    # scout returned postings but the LLM step never ran (because of an
    # earlier error, or candidates was empty after dedup), nothing gets
    # marked seen for that scout — so next run will retry instead of
    # silently skipping forever.
    if candidates:
        # Mark the scored ones as seen
        dedup.mark_seen(candidates)
        logger.info("Marked %d postings as seen.", len(candidates))
    else:
        logger.info("Nothing to mark as seen this run.")

    dedup.close()
    health.close()
    logger.info("=== Done in %s ===", finished_utc - started_utc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
