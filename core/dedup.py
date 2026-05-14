"""SQLite-backed dedup store.

Tracks which postings we've already shown to the user. The DB file
(`data/seen.sqlite`) is committed back to the repo by the GitHub Actions
workflow so state persists across runs.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Iterable

from .models import Posting


SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_postings (
    uid          TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    title        TEXT NOT NULL,
    institution  TEXT,
    url          TEXT NOT NULL,
    first_seen   TEXT NOT NULL,
    fit_score    INTEGER
);

CREATE INDEX IF NOT EXISTS idx_first_seen ON seen_postings(first_seen);
"""


class DedupStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def is_seen(self, uid: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM seen_postings WHERE uid = ? LIMIT 1", (uid,)
        )
        return cur.fetchone() is not None

    def filter_new(self, postings: Iterable[Posting]) -> list[Posting]:
        """Return only postings we haven't seen before."""
        return [p for p in postings if not self.is_seen(p.uid)]

    def mark_seen(self, postings: Iterable[Posting]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (p.uid, p.source, p.title, p.institution, p.url, now, p.fit_score)
            for p in postings
        ]
        self._conn.executemany(
            "INSERT OR IGNORE INTO seen_postings "
            "(uid, source, title, institution, url, first_seen, fit_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def close(self):
        self._conn.close()
