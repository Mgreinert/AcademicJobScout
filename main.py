"""
Academic Job Scout — main orchestrator.

Run every Monday by GitHub Actions; can also be run locally:

    export ANTHROPIC_API_KEY=...
    python main.py

Pipeline:
  1. Instantiate scouts: every aggregator + every university from YAML.
  2. Fetch each (wrapped in try/except so one bad source can't kill the run).
  3. Record per-source health (ok / fetch_failed / parse_empty / zero_streak).
  4. Deduplicate against the SQLite store.
  5. Score the new postings with Claude (Haiku).
  6. Drop low-scoring ones, build a markdown digest grouped by score,
     append source-health footer.
  7. Send (currently stubbed to disk).
  8. Persist new postings as "seen" so they don't reappear next week.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Make sibling packages importable when run as `python main.py`
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.dedup import DedupStore
from core.digest import build_digest
from core.health import HealthStore, RunStatus
from core.mailer import send_digest
from core.models import Posting
from core.relevance import score_postings

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


def main() -> int:
    logger.info("=== Academic Job Scout starting ===")

    dedup = DedupStore(DB_PATH)
    health = HealthStore(DB_PATH)

    scouts = gather_scouts()
    logger.info("Loaded %d scouts: %s", len(scouts), [s.name for s in scouts])

    all_postings: list[Posting] = []
    reports = []
    for scout in scouts:
        logger.info("→ Running %s", scout.name)
        postings, report = run_scout(scout, health)
        logger.info("   %s → %d postings, status=%s",
                    scout.name, len(postings), report.status.value)
        all_postings.extend(postings)
        reports.append(report)

    # Deduplicate against history
    new_postings = dedup.filter_new(all_postings)
    logger.info("Total fetched: %d, new (unseen): %d",
                len(all_postings), len(new_postings))

    # Score with Claude (only if any new postings — saves API calls)
    if new_postings:
        if not PROFILE_PATH.exists():
            logger.warning(
                "No profile at %s — relevance filter will be poor. "
                "Add a real CV/profile.", PROFILE_PATH,
            )
            # Write a tiny placeholder so the call doesn't error
            PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
            PROFILE_PATH.write_text(
                "Academic researcher, field unspecified.", encoding="utf-8"
            )
        scored = score_postings(new_postings, PROFILE_PATH)
        logger.info("Kept %d of %d after relevance filter (score >= 3)",
                    len(scored), len(new_postings))
    else:
        scored = []

    # Build digest and send
    subject, body = build_digest(scored, reports)
    status = send_digest(subject, body)
    logger.info("Mailer: %s", status)

    # Mark all *fetched* (not just kept) postings as seen, so next run won't
    # re-process them through the LLM even if they were filtered out.
    dedup.mark_seen(all_postings)

    dedup.close()
    health.close()
    logger.info("=== Done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
