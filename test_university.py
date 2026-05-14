"""
Test a single university entry in config/universities.yaml without running
the full pipeline. Useful for tuning CSS selectors.

Usage:
    python test_university.py "University of Washington"
    python test_university.py "University of Washington" --raw   # dump HTML
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scouts.universities import load_university_scouts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "name",
        help="University name from config/universities.yaml "
             "(partial match, case-insensitive)",
    )
    parser.add_argument(
        "--raw", action="store_true",
        help="Dump fetched HTML to /tmp/<name>.html for selector debugging",
    )
    args = parser.parse_args()

    config = Path(__file__).resolve().parent / "config" / "universities.yaml"
    scouts = load_university_scouts(config)

    needle = args.name.lower()
    matches = [s for s in scouts if needle in s.display_name.lower()]
    if not matches:
        print(f"No university in config matched {args.name!r}.")
        print("Available:")
        for s in scouts:
            print(f"  - {s.display_name}")
        return 1
    if len(matches) > 1:
        print(f"Ambiguous match for {args.name!r}:")
        for s in matches:
            print(f"  - {s.display_name}")
        return 1

    scout = matches[0]
    print(f"Testing: {scout.display_name}")
    print(f"  URL:           {scout.jobs_url}")
    print(f"  Fetcher:       {scout.fetcher}")
    print(f"  Post selector: {scout.posting_selector}")
    print(f"  Title sel:     {scout.title_selector}")
    print(f"  Link sel:      {scout.link_selector}")
    print(f"  must_match:    {scout.must_match}")
    print()

    if args.raw:
        if scout.fetcher == "playwright":
            html = scout._fetch_playwright(scout.jobs_url)
        else:
            html = scout._fetch_requests(scout.jobs_url)
        out = Path("/tmp") / f"{scout.display_name.replace(' ', '_')}.html"
        out.write_text(html, encoding="utf-8")
        print(f"Wrote raw HTML to {out} ({len(html):,} bytes)")
        return 0

    try:
        postings = scout.fetch()
    except Exception as e:
        print(f"FETCH FAILED: {type(e).__name__}: {e}")
        return 2

    print(f"Found {len(postings)} postings after pre-filter.")
    for i, p in enumerate(postings[:20], 1):
        print(f"  [{i}] {p.title}")
        print(f"      {p.url}")
        if p.location:
            print(f"      ({p.location})")
    if len(postings) > 20:
        print(f"  ... and {len(postings) - 20} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
