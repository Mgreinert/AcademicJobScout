"""Per-source health tracking.

Distinguishes three failure modes:
- FETCH_FAILED: network/auth/HTTP error
- PARSE_EMPTY: fetch succeeded but selectors returned nothing (HTML likely changed)
- ZERO_RESULTS_STREAK: ran cleanly but found 0 postings for N consecutive weeks
                       (possibly a quietly broken selector, possibly genuinely quiet)

The same SQLite DB as dedup is used; one table per concern.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


ZERO_RESULTS_WARN_AFTER = 3  # consecutive weeks of 0 results before warning


class RunStatus(str, Enum):
    OK = "ok"
    FETCH_FAILED = "fetch_failed"
    PARSE_EMPTY = "parse_empty"


SCHEMA = """
CREATE TABLE IF NOT EXISTS source_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    run_time     TEXT NOT NULL,
    status       TEXT NOT NULL,
    n_postings   INTEGER NOT NULL DEFAULT 0,
    error_msg    TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_runs_source ON source_runs(source);
CREATE INDEX IF NOT EXISTS idx_source_runs_time ON source_runs(run_time);
"""


@dataclass
class SourceReport:
    source: str
    status: RunStatus
    n_postings: int
    zero_results_streak: int
    error_msg: Optional[str] = None

    @property
    def emoji(self) -> str:
        if self.status == RunStatus.FETCH_FAILED:
            return "❌"
        if self.status == RunStatus.PARSE_EMPTY:
            return "⚠️"
        if (
            self.status == RunStatus.OK
            and self.n_postings == 0
            and self.zero_results_streak >= ZERO_RESULTS_WARN_AFTER
        ):
            return "⚠️"
        return "✅"

    @property
    def summary(self) -> str:
        if self.status == RunStatus.FETCH_FAILED:
            return f"fetch failed: {self.error_msg or 'unknown error'}"
        if self.status == RunStatus.PARSE_EMPTY:
            return "fetched ok but parsed 0 postings (selectors may be broken)"
        if (
            self.n_postings == 0
            and self.zero_results_streak >= ZERO_RESULTS_WARN_AFTER
        ):
            return (
                f"0 postings ({self.zero_results_streak} weeks in a row "
                f"— may be silently broken)"
            )
        return f"{self.n_postings} postings found"


class HealthStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def record_run(
        self,
        source: str,
        status: RunStatus,
        n_postings: int,
        error_msg: Optional[str] = None,
    ) -> SourceReport:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO source_runs (source, run_time, status, n_postings, error_msg) "
            "VALUES (?, ?, ?, ?, ?)",
            (source, now, status.value, n_postings, error_msg),
        )
        self._conn.commit()
        return SourceReport(
            source=source,
            status=status,
            n_postings=n_postings,
            zero_results_streak=self._zero_results_streak(source),
            error_msg=error_msg,
        )

    def _zero_results_streak(self, source: str) -> int:
        """Count consecutive most-recent runs where status=ok and n_postings=0."""
        cur = self._conn.execute(
            "SELECT status, n_postings FROM source_runs "
            "WHERE source = ? ORDER BY id DESC LIMIT 20",
            (source,),
        )
        streak = 0
        for status, n in cur.fetchall():
            if status == RunStatus.OK.value and n == 0:
                streak += 1
            else:
                break
        return streak

    def close(self):
        self._conn.close()
