"""Email digest builder.

Produces a markdown-formatted message body grouping postings by fit score,
followed by a source-health status block so silently-broken scrapers get
surfaced.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

from .health import SourceReport
from .models import Posting


def build_digest(
    postings: Iterable[Posting],
    source_reports: Iterable[SourceReport],
    run_date: date | None = None,
) -> tuple[str, str]:
    """Return (subject, body) for the weekly email."""
    postings = list(postings)
    source_reports = list(source_reports)
    run_date = run_date or date.today()

    n = len(postings)
    top_score = max((p.fit_score or 0) for p in postings) if postings else 0
    if n == 0:
        subject = f"Academic Job Scout — {run_date.isoformat()} — no new matches"
    elif top_score >= 5:
        subject = f"Academic Job Scout — {run_date.isoformat()} — {n} new ({top_score}★ top)"
    else:
        subject = f"Academic Job Scout — {run_date.isoformat()} — {n} new matches"

    lines: list[str] = []
    lines.append(f"# Academic Job Scout — {run_date.isoformat()}")
    lines.append("")

    if not postings:
        lines.append("No new matches this week.")
    else:
        # Group by score, descending
        by_score: dict[int, list[Posting]] = {}
        for p in postings:
            by_score.setdefault(p.fit_score or 0, []).append(p)

        for score in sorted(by_score.keys(), reverse=True):
            label = {5: "Excellent fit", 4: "Strong fit", 3: "Worth a look"}.get(
                score, f"Score {score}"
            )
            lines.append(f"## {label} ({score}★) — {len(by_score[score])}")
            lines.append("")
            for p in by_score[score]:
                lines.append(f"### [{p.title}]({p.url})")
                lines.append(f"**{p.institution}**"
                             + (f" — {p.location}" if p.location else ""))
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

    # Source health footer
    lines.append("---")
    lines.append("## Source health")
    lines.append("")
    for r in source_reports:
        lines.append(f"- {r.emoji} **{r.source}** — {r.summary}")
    lines.append("")
    lines.append("_If a source is consistently ⚠️ or ❌, the scraper likely needs maintenance._")

    return subject, "\n".join(lines)
