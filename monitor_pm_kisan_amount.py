"""Optional detection layer -- automated source-of-truth monitor.

Fetches https://pmkisan.gov.in and scans the page text for the expected
'Rs 6,000' benefit amount. If the string can NO LONGER be found on the
official page, that's a strong signal the scheme may have changed and
our corpus (pm_kisan.md) may need review.

NOTE: web scraping is FRAGILE. Government sites change layout without
notice, add JavaScript-rendered content, or block scrapers. This script
is a starting point, not a production-grade monitor. For real production:
    * use an official API if one exists (data.gov.in for MSP data)
    * subscribe to PIB press releases via RSS
    * fall back to scraping only when the above are unavailable
    * always alert on 'unknown status' -- silent monitors are useless

Run:
    python monitor_pm_kisan_amount.py

Exit codes (useful for cron):
    0  -> expected amount was found on the page (OK)
    1  -> expected amount NOT found (MANUAL REVIEW)
    2  -> could not fetch page at all (network / firewall issue)

Example cron entry (Monday 7 AM):
    0 7 * * 1 /home/opc/agri-agent/.venv/bin/python \
        /home/opc/agri-agent/monitor_pm_kisan_amount.py \
        || echo "check pm-kisan corpus" | mail -s "Agri-Agent alert" you@example.com
"""

from __future__ import annotations

import re
import sys
from datetime import datetime

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")


# ---------------------------------------------------------------------------
# What we expect to still be true on the official page
# ---------------------------------------------------------------------------
SOURCE_URL = "https://pmkisan.gov.in/"

# Patterns considered "match": if ANY of these still appears on the page,
# we assume the Rs 6,000/year fact is still valid. We use several variants
# because sites style numbers inconsistently.
EXPECTED_PATTERNS = [
    r"Rs\.?\s*6[,.]?000",              # Rs 6,000 / Rs.6000 / Rs 6000
    r"Rs\.?\s*6\s*thousand",           # "Rs 6 thousand"
    r"\b6000\s*per\s*annum",           # "6000 per annum"
    r"\b6,000/?-?\s*per\s*year",       # "6,000/- per year"
    r"₹\s*6[,.]?000",                  # ₹6,000
]

REQUEST_TIMEOUT_S = 15
USER_AGENT = "AgriAgentCorpusMonitor/1.0 (+github.com/manishjsh2706/agri-agent)"


class MonitorResult:
    """Outcome of one monitor run."""

    STATUS_OK      = "OK"           # expected amount found on page
    STATUS_MISSING = "MISSING"      # page fetched but expected amount not found
    STATUS_NET     = "NETWORK"      # could not fetch the page at all

    def __init__(self, status: str, matched_pattern: str = "",
                 http_status: int = 0, error: str = "",
                 preview: str = ""):
        self.status          = status
        self.matched_pattern = matched_pattern
        self.http_status     = http_status
        self.error           = error
        self.preview         = preview
        self.ts              = datetime.utcnow().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------
def fetch_page(url: str) -> tuple[str, int, str]:
    """Fetch the page. Returns (body_text, http_status, error_msg)."""
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT_S,
                         headers={"User-Agent": USER_AGENT})
        return r.text, r.status_code, ""
    except Exception as e:
        return "", 0, f"{type(e).__name__}: {e}"


def find_amount_in_body(body: str) -> str:
    """Return the first matching pattern (if any) that appears in the body."""
    if not body:
        return ""
    haystack = body.replace("&nbsp;", " ").replace("\xa0", " ")
    for pat in EXPECTED_PATTERNS:
        if re.search(pat, haystack, re.IGNORECASE):
            return pat
    return ""


def check_pm_kisan_amount() -> MonitorResult:
    body, http_status, err = fetch_page(SOURCE_URL)
    if err:
        return MonitorResult(MonitorResult.STATUS_NET,
                             http_status=http_status, error=err)
    if http_status >= 400:
        return MonitorResult(MonitorResult.STATUS_NET,
                             http_status=http_status,
                             error=f"HTTP {http_status}")

    matched = find_amount_in_body(body)
    if matched:
        # Small preview so the human alert has context
        preview = _first_matching_snippet(body, matched)
        return MonitorResult(MonitorResult.STATUS_OK,
                             matched_pattern=matched,
                             http_status=http_status,
                             preview=preview)

    return MonitorResult(MonitorResult.STATUS_MISSING,
                         http_status=http_status,
                         preview=body[:400].replace("\n", " ")[:400])


def _first_matching_snippet(body: str, pattern: str) -> str:
    """Return ~100 characters around the first match, for context."""
    m = re.search(pattern, body, re.IGNORECASE)
    if not m:
        return ""
    start = max(0, m.start() - 40)
    end   = min(len(body), m.end() + 40)
    return body[start:end].replace("\n", " ").strip()


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _print_report(res: MonitorResult) -> None:
    print()
    print(f"PM-Kisan source monitor  ({res.ts} UTC)")
    print(f"URL: {SOURCE_URL}")
    print(f"HTTP status: {res.http_status}")
    print(f"Result: {res.status}")

    if res.status == MonitorResult.STATUS_OK:
        print(f"Matched pattern: {res.matched_pattern!r}")
        print(f"Snippet: ...{res.preview}...")
        print("Corpus fact 'Rs 6,000/year' still consistent with official page.")
    elif res.status == MonitorResult.STATUS_MISSING:
        print("EXPECTED AMOUNT NOT FOUND ON PAGE.")
        print("Possible reasons:")
        print("  1. Site layout changed and moved the amount elsewhere")
        print("  2. Site now uses different formatting (e.g. Rs 8,000)")
        print("  3. Site is JS-rendered and requests didn't get the real HTML")
        print("Recommended action: manually visit the page and verify.")
        print(f"Page preview: {res.preview[:400]}...")
    else:
        print(f"NETWORK ERROR: {res.error}")
        print("Cannot determine corpus freshness. Try again later.")


def main() -> int:
    res = check_pm_kisan_amount()
    _print_report(res)
    return {
        MonitorResult.STATUS_OK:      0,
        MonitorResult.STATUS_MISSING: 1,
        MonitorResult.STATUS_NET:     2,
    }[res.status]


if __name__ == "__main__":
    sys.exit(main())
