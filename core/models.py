"""Unified Posting model. Every scout returns a list of these."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional


@dataclass
class Posting:
    """A single job posting from any source.

    The `source` field identifies which scout produced it (e.g. 'euraxess',
    'university:NUS'). The `uid` is a stable hash used for deduplication so the
    same posting appearing in two sources, or appearing across weeks, only
    gets shown once.
    """

    source: str                    # e.g. "euraxess", "university:NUS"
    title: str
    institution: str
    url: str
    description: str = ""          # short snippet, used by the relevance filter
    location: Optional[str] = None
    deadline: Optional[date] = None
    posted_date: Optional[date] = None

    # Populated by the relevance filter, not by scouts
    fit_score: Optional[int] = None        # 1-5
    fit_rationale: Optional[str] = None    # one-line reason

    uid: str = field(init=False)

    def __post_init__(self):
        # UID is stable across runs and across sources: same URL → same posting.
        # We also fold in the title because some aggregators reuse a generic
        # "apply here" URL for many postings.
        basis = f"{self.url}::{self.title.strip().lower()}"
        self.uid = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        # Dates aren't JSON-serializable; isoformat them for storage
        if self.deadline:
            d["deadline"] = self.deadline.isoformat()
        if self.posted_date:
            d["posted_date"] = self.posted_date.isoformat()
        return d
