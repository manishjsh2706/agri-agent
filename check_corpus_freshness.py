"""Detection layer for RAG corpus staleness.

Scans schemes/*.md for "Last verified" dates and flags any doc older than
a threshold (default 90 days). Meant to be run weekly (via cron or
manually) so you catch stale corpus entries before farmers do.

Run:
    python check_corpus_freshness.py                 # default 90-day threshold
    python check_corpus_freshness.py --days 60       # stricter threshold
    python check_corpus_freshness.py --quiet         # only show stale docs
    python check_corpus_freshness.py --json          # machine-readable output

Exit codes (useful for cron):
    0  -> all docs are fresh
    1  -> at least one doc is stale (cron can email you)

Example cron entry (every Monday 8 AM):
    0 8 * * 1 /home/opc/agri-agent/.venv/bin/python \
        /home/opc/agri-agent/check_corpus_freshness.py \
        || mail -s "Agri-Agent stale corpus" you@example.com
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCHEMES_DIR = "schemes"
DEFAULT_STALE_DAYS = 90            # 3 months
# Recognised date formats in "Last verified" lines.
DATE_FORMATS = [
    "%d %B %Y",       # "15 July 2026"
    "%B %Y",          # "July 2026"
    "%d/%m/%Y",       # "15/07/2026"
    "%Y-%m-%d",       # "2026-07-15"
    "%d-%m-%Y",       # "15-07-2026"
]


# ---------------------------------------------------------------------------
# Data class -- one row per scheme file
# ---------------------------------------------------------------------------
class SchemeFreshness:
    """Freshness info for one scheme file."""

    def __init__(self, file: Path, verified_date: Optional[date],
                 age_days: Optional[int], is_stale: bool, raw_line: str):
        self.file          = file
        self.verified_date = verified_date
        self.age_days      = age_days
        self.is_stale      = is_stale
        self.raw_line      = raw_line

    def to_dict(self) -> dict:
        return {
            "file":          self.file.name,
            "verified_date": self.verified_date.isoformat() if self.verified_date else None,
            "age_days":      self.age_days,
            "is_stale":      self.is_stale,
            "raw_line":      self.raw_line,
        }


# ---------------------------------------------------------------------------
# Core parsing
# ---------------------------------------------------------------------------
def _extract_verified_date(text: str) -> tuple[Optional[date], str]:
    """Find the 'Last verified' line and parse its date.

    Returns (parsed_date, raw_line). If we can't find or parse the line,
    parsed_date is None but raw_line explains what we saw.
    """
    # Look for a line like: **Last verified:** July 2026.
    match = re.search(
        r"\*?\*?Last verified:?\*?\*?\s*[:\-]?\s*(.+)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None, "(no 'Last verified' line found)"

    raw = match.group(1).strip().rstrip(".").rstrip(",").strip()

    # Try each known date format.
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt).date()
            return parsed, raw
        except ValueError:
            continue

    # Handle "July 2026" (month + year without day) explicitly
    # by prepending "1 " and retrying with "%d %B %Y".
    try:
        parsed = datetime.strptime("1 " + raw, "%d %B %Y").date()
        return parsed, raw
    except ValueError:
        pass

    return None, raw


def analyse_file(file_path: Path, stale_days: int) -> SchemeFreshness:
    """Read one scheme file and classify its freshness."""
    text = file_path.read_text(encoding="utf-8")
    verified, raw = _extract_verified_date(text)

    if verified is None:
        return SchemeFreshness(
            file=file_path,
            verified_date=None,
            age_days=None,
            is_stale=True,          # unknown date -> treat as stale
            raw_line=raw,
        )

    age = (date.today() - verified).days
    return SchemeFreshness(
        file=file_path,
        verified_date=verified,
        age_days=age,
        is_stale=age > stale_days,
        raw_line=raw,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _emoji(stale: bool, age_days: Optional[int], stale_days: int) -> str:
    if age_days is None:
        return "[!]"
    if stale:
        return "[STALE]"
    if age_days > stale_days // 2:
        return "[WARN ]"
    return "[FRESH]"


def print_human_report(rows: list[SchemeFreshness], stale_days: int,
                       quiet: bool) -> None:
    stale_count = sum(1 for r in rows if r.is_stale)
    total       = len(rows)

    print()
    print(f"Corpus freshness scan  ({date.today().isoformat()})")
    print(f"Threshold: {stale_days} days")
    print(f"Files scanned: {total}   Stale: {stale_count}")
    print("-" * 70)

    for r in rows:
        if quiet and not r.is_stale:
            continue
        tag  = _emoji(r.is_stale, r.age_days, stale_days)
        name = r.file.name
        if r.verified_date is None:
            desc = f"unknown date  ({r.raw_line})"
        else:
            desc = f"verified {r.verified_date.isoformat()}  ({r.age_days} days old)"
        print(f"  {tag}  {name:<25}  {desc}")

    print("-" * 70)
    if stale_count == 0:
        print("All docs are fresh. No action needed.")
    else:
        print(f"{stale_count} doc(s) need review. See list above.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=SCHEMES_DIR,
                        help=f"Corpus directory (default: {SCHEMES_DIR})")
    parser.add_argument("--days", type=int, default=DEFAULT_STALE_DAYS,
                        help=f"Stale-after N days (default: {DEFAULT_STALE_DAYS})")
    parser.add_argument("--quiet", action="store_true",
                        help="Only print stale docs.")
    parser.add_argument("--json", action="store_true",
                        help="Print machine-readable JSON instead of a table.")
    args = parser.parse_args()

    schemes_dir = Path(args.dir)
    if not schemes_dir.exists():
        print(f"[error] directory not found: {schemes_dir}", file=sys.stderr)
        return 2

    files = sorted(schemes_dir.glob("*.md"))
    files = [f for f in files if f.name.lower() != "readme.md"]
    if not files:
        print(f"[error] no .md files in {schemes_dir}", file=sys.stderr)
        return 2

    rows = [analyse_file(f, args.days) for f in files]

    if args.json:
        print(json.dumps([r.to_dict() for r in rows], indent=2))
    else:
        print_human_report(rows, args.days, args.quiet)

    # Exit code: 0 if all fresh, 1 if any stale (for cron / CI)
    any_stale = any(r.is_stale for r in rows)
    return 1 if any_stale else 0


if __name__ == "__main__":
    sys.exit(main())
