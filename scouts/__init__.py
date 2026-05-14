"""Scout base class.

A scout is anything that knows how to pull a list of Postings from a source.
Each subclass implements `fetch()`. The orchestrator wraps every fetch call
in try/except and records the result via health.py, so individual scout
failures never kill the whole run.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import Posting


class Scout(ABC):
    name: str  # short identifier used in source-health reports

    @abstractmethod
    def fetch(self) -> list[Posting]:
        """Return a list of Postings. Raise on fetch/parse failure."""
        ...
