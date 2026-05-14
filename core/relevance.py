"""LLM-based relevance scoring.

Sends each new posting plus the researcher's profile to Claude Haiku and
gets back a 1-5 fit score with a one-line rationale. Haiku is plenty smart
for this task and costs roughly 5-15 cents per weekly run.

Postings scoring below MIN_SCORE_TO_INCLUDE are dropped from the digest.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Iterable

import anthropic

from .models import Posting


logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"
MIN_SCORE_TO_INCLUDE = 3


SYSTEM_PROMPT = """You are an academic job-fit evaluator. You are given:

1. A researcher's profile (CV summary, research interests, career stage, preferences).
2. A single job posting.

Your job: rate how well the posting fits the researcher on a 1-5 scale, and
give a one-line rationale (≤20 words).

Scale:
  5 = excellent fit (clearly in their field, right career stage, no obvious blockers)
  4 = strong fit (mostly aligned, maybe one mismatch)
  3 = possible fit (adjacent field or area, worth a look)
  2 = weak fit (some overlap, but probably not their thing)
  1 = no fit (different field, wrong stage, or excluded by their preferences)

Be honest. Most postings will be 1-2. A 5 should be rare.

Reply with ONLY a JSON object, no other text:
{"score": <int 1-5>, "rationale": "<one-line reason>"}
"""


def _build_user_message(profile: str, posting: Posting) -> str:
    return (
        f"=== RESEARCHER PROFILE ===\n{profile}\n\n"
        f"=== JOB POSTING ===\n"
        f"Title: {posting.title}\n"
        f"Institution: {posting.institution}\n"
        f"Location: {posting.location or 'unknown'}\n"
        f"Source: {posting.source}\n"
        f"Description: {posting.description or '(no description)'}\n"
        f"URL: {posting.url}\n"
    )


def _parse_response(text: str) -> tuple[int, str]:
    """Parse Claude's JSON response, with a fallback for stray prose."""
    # Strip code fences if Claude wrapped the JSON
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        data = json.loads(text)
        score = int(data["score"])
        rationale = str(data["rationale"]).strip()
        if not 1 <= score <= 5:
            raise ValueError(f"score out of range: {score}")
        return score, rationale
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        logger.warning("Failed to parse relevance response: %s | text=%r", e, text)
        # Conservative fallback: score 2 so it's logged but not surfaced
        return 2, f"(parse error: {e})"


def score_postings(
    postings: Iterable[Posting],
    profile_path: Path,
    client: anthropic.Anthropic | None = None,
) -> list[Posting]:
    """Score each posting in place. Returns postings sorted by fit_score desc,
    filtered to those at or above MIN_SCORE_TO_INCLUDE.
    """
    postings = list(postings)
    if not postings:
        return []

    profile = Path(profile_path).read_text(encoding="utf-8")
    client = client or anthropic.Anthropic(
        api_key=os.environ.get("ANTHROPIC_API_KEY")
    )

    for p in postings:
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=200,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": _build_user_message(profile, p)}],
            )
            # resp.content is a list of content blocks; join the text ones
            text = "".join(
                block.text for block in resp.content if getattr(block, "type", None) == "text"
            )
            score, rationale = _parse_response(text)
            p.fit_score = score
            p.fit_rationale = rationale
        except Exception as e:
            logger.error("Relevance API call failed for %s: %s", p.title, e)
            p.fit_score = 2
            p.fit_rationale = f"(scoring failed: {e})"

    # Filter and sort
    kept = [p for p in postings if (p.fit_score or 0) >= MIN_SCORE_TO_INCLUDE]
    kept.sort(key=lambda p: p.fit_score or 0, reverse=True)
    return kept
