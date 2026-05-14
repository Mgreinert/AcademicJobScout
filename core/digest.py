"""
Email digest builder.

Produces a markdown-formatted message body with:
  1. Header with run start/finish time (UTC + Zurich local).
  2. Postings kept after LLM scoring, grouped by score.
  3. "What the scrapers saw" — a per-source breakdown of every posting the
     scrapers found, with each one's fate (kept / scored-low / seen-before).
     This is the diagnostic section: it lets you see whether the scraper
     is finding anything at all, independently of dedup and LLM filtering.
  4. Source health footer — per-scraper success/failure flags.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Literal, Optional

from .health import SourceReport
from .models import Posting


Fate = Literal["kept", "scored-low", "seen-before", "to-score"]


@dataclass
class PostingTrace:
    """The journey of one posting through the pipeline.

    fate:
      "seen-before" — was in the dedup DB; LLM never looked at it
      "to-score"    — passed dedup; awaiting LLM (transient state)
      "scored-low"  — LLM scored it below MIN_SCORE_TO_INCLUDE; dropped
      "kept"        — LLM scored it high enough; appears in the digest
    """
    posting: Posting
    fate: Fate
    fit_score: Optional[int] = None
    fit_rationale: Optional[str] = None

    @property
    def emoji(self) -> str:
        return {
            "kept": "⭐",
            "scored-low": "·",
            "seen-before": "↻",
            "to-score": "?",
        }.get(self.fate, "?")


def build_digest(
    kept_postings: Iterable[Posting],
    traces: Iterable[PostingTrace],
    source_reports: Iterable[SourceReport],
    started_utc: datetime,
    finished_utc: datetime,
    started_local: datetime,
    finished_local: datetime,
) -> tuple[str, str]:
    """Return (subject, body) for the weekly email."""
    kept_postings = list(kept_postings)
    traces = list(traces)
    source_reports = list(source_reports)

    # --- Subject ---
    n = len(kept_postings)
    date_str = started_local.date().isoformat()
    top_score = max((p.fit_score or 0) for p in kept_postings) if kept_postings else 0
    if n == 0:
        subject = f"Academic Job Scout — {date_str} — no new matches"
    elif top_score >= 5:
        subject = f"Academic Job Scout — {date_str} — {n} new ({top_score}★ top)"
    else:
        subject = f"Academic Job Scout — {date_str} — {n} new matches"

    # --- Body ---
    lines: list[str] = []

    # Header with timestamp
    lines.append(f"# Academic Job Scout — {date_str}")
    lines.append("")
    lines.append(
        f"Run started: **{started_local.strftime('%Y-%m-%d %H:%M:%S %Z')}** "
        f"(UTC: {started_utc.strftime('%H:%M:%S')})  "
    )
    duration = finished_utc - started_utc
    lines.append(
        f"Duration: {int(duration.total_seconds())}s  "
    )
    lines.append("")

    # --- Section 1: kept postings ---
    if not kept_postings:
        lines.append("**No new matches this week.**")
        lines.append("")
        lines.append("Check the 'What the scrapers saw' section below to "
                     "verify the scrapers found content and the LLM filter "
                     "is working as expected.")
        lines.append("")
    else:
        by_score: dict[int, list[Posting]] = {}
        for p in kept_postings:
            by_score.setdefault(p.fit_score or 0, []).append(p)
        for score in sorted(by_score.keys(), reverse=True):
            label = {5: "Excellent fit", 4: "Strong fit", 3: "Worth a look"}.get(
                score, f"Score {score}"
            )
            lines.append(f"## {label} ({score}★) — {len(by_score[score])}")
            lines.append("")
            for p in by_score[score]:
                lines.append(f"### [{p.title}]({p.url})")
                lines.append(
                    f"**{p.institution}**"
                    + (f" — {p.location}" if p.location else "")
                )
                if p.deadline:
                    lines.append(f"_Deadline: {p.deadline.isoformat()}_")
                if p.fit_rationale:
                    lines.append(f"> {p.fit_rationale}")
                if p.description:
                    snippet = p.description[:300]
                    if len(p.description) > 300:
                        snippet += "..."
                    lines.append("")
                    lines.append(snippet)
                lines.append(f"_Source: {p.source}_")
                lines.append("")

    # --- Section 2: What the scrapers saw (diagnostic) ---
    lines.append("---")
    lines.append("## What the scrapers saw")
    lines.append("")
    lines.append(
        "Every posting the scrapers found this run, grouped by source. "
        "Use this to check whether each scraper is seeing content at all, "
        "independently of dedup and LLM filtering."
    )
    lines.append("")
    lines.append("**Fate legend**: ⭐ kept in digest · · scored low (dropped) "
                 "· ↻ already seen in a prior run (LLM skipped)")
    lines.append("")

    by_source: dict[str, list[PostingTrace]] = defaultdict(list)
    for t in traces:
        by_source[t.posting.source].append(t)

    if not by_source:
        lines.append("_No postings were returned by any scraper this run._")
        lines.append("")

    for source in sorted(by_source.keys()):
        items = by_source[source]
        counts = defaultdict(int)
        for t in items:
            counts[t.fate] += 1
        summary = ", ".join(
            f"{n} {label}"
            for label, n in (
                ("kept", counts["kept"]),
                ("scored-low", counts["scored-low"]),
                ("seen-before", counts["seen-before"]),
            )
            if n
        ) or "none"
        lines.append(f"### {source} — {len(items)} total ({summary})")
        lines.append("")
        for t in items:
            score_str = ""
            if t.fit_score is not None:
                score_str = f" [{t.fit_score}★]"
            line = f"- {t.emoji}{score_str} **{t.posting.title}**"
            if t.posting.institution and t.posting.institution != "(unknown)":
                line += f" — {t.posting.institution}"
            lines.append(line)
            if t.fit_rationale:
                lines.append(f"  > _{t.fit_rationale}_")
        lines.append("")

    # --- Section 3: Source health ---
    lines.append("---")
    lines.append("## Source health")
    lines.append("")
    for r in source_reports:
        lines.append(f"- {r.emoji} **{r.source}** — {r.summary}")
    lines.append("")
    lines.append("_If a source is consistently ⚠️ or ❌, the scraper likely "
                 "needs maintenance._")

    return subject, "\n".join(lines)
