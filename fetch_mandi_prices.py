#!/usr/bin/env python3
"""
STEP 1 TEST SCRIPT  --  Agricultural Market Intelligence Agent
==============================================================
Fetches daily mandi (wholesale market) prices for selected crops in a
chosen district from the Government of India open-data API (data.gov.in).

WHAT THIS SCRIPT PROVES
-----------------------
  1. That you CAN pull real mandi price data programmatically.
  2. HOW FRESH the data is  -> look at the "Arrival date" column and at
     the "DATA FRESHNESS" line printed at the end.
  3. WHICH markets and crops near you actually have data.

If this script prints a table of real prices, your whole project is
viable. If it prints nothing, you have learned that on day one.

----------------------------------------------------------------------
BEFORE YOU RUN
----------------------------------------------------------------------
  1. Install the one dependency (open a terminal / command prompt):

         pip install requests

  2. Get your OWN free API key (takes 2 minutes):
         - Sign up at  https://data.gov.in
         - Open your profile  ->  "My Account"  ->  copy your API key
         - Paste it into the API_KEY line below.

     A public SAMPLE key is filled in so you can test immediately, but
     it is shared and rate-limited -- replace it with your own key.

  3. Run the script:

         python fetch_mandi_prices.py

----------------------------------------------------------------------
"""

import sys

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")

from db import init_db, save_prices, db_summary


# ======================================================================
# CONFIG  --  edit these five lines, nothing else
# ======================================================================
API_KEY  = "579b464db66ec23bdd0000012be4aaa5f0ca4daa6fcc8eba56158149"  # your data.gov.in key
STATE    = "Maharashtra"
DISTRICT = "Pune"

# Commodity names MUST match the data.gov.in spelling exactly.
# These five are the portal's spellings for common Maharashtra crops.
CROPS = ["Onion", "Tomato", "Soyabean", "Wheat", "Arhar (Tur/Red Gram)(Whole)"]
# ======================================================================


# data.gov.in resource: "Current Daily Price of Various Commodities
# from Various Markets (Mandi)".
RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"
BASE_URL = f"https://api.data.gov.in/resource/{RESOURCE_ID}"


def get_field(record, *possible_names):
    """The API has used different capitalisations over time
    (e.g. 'state' vs 'State'). Try each spelling and return the first hit."""
    for name in possible_names:
        if name in record and record[name] not in (None, ""):
            return record[name]
    return ""


# --- Network settings ----------------------------------------------------
# data.gov.in is slow with big responses, so we fetch in small PAGES.
PAGE_SIZE   = 50           # rows per request (small page = fast, no timeout)
MAX_ROWS    = 2000         # safety cap on total rows pulled
TIMEOUT     = (10, 60)     # (connect, read) seconds
MAX_RETRIES = 3
PROXY       = ""           # set e.g. "http://proxy.company.com:8080" only if
                           # you are behind a company proxy; leave "" otherwise

# Some government servers stall requests that don't look like a real browser.
# These headers make the script introduce itself as Chrome.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
}
# -------------------------------------------------------------------------


def api_get(params, show_url=False):
    """GET one page from the API, with retries on timeout."""
    prepared = requests.Request("GET", BASE_URL, params=params).prepare()
    if show_url:
        print(f"\nRequest URL (paste into a browser to check):\n{prepared.url}\n")

    proxies = {"http": PROXY, "https": PROXY} if PROXY else None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(prepared.url, timeout=TIMEOUT,
                                 proxies=proxies, headers=HEADERS)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.Timeout:
            print(f"  Timed out (attempt {attempt}/{MAX_RETRIES}) -- retrying ...")
        except requests.exceptions.RequestException as e:
            sys.exit(f"\nAPI request failed: {e}\n"
                     f"Check your internet connection and your API key.")
    sys.exit("\nThe API kept timing out even on a small page.\n"
             "This usually means a proxy or firewall is interfering.\n"
             "Try: (1) a different network e.g. a mobile hotspot, or\n"
             "     (2) set the PROXY value near the top of this script.")


def fetch_all(filters):
    """Fetch ALL rows for the given filters, one small page at a time.
    Small pages avoid the timeouts caused by asking for 1000 rows at once.

    IMPORTANT: filter names must use the field IDs the API EXPOSES, not the
    display names. The dataset's 'field_exposed' list shows the real IDs are
    'state.keyword' and 'district' -- using 'State'/'District' returns 0 rows.
    """
    rows = []
    offset = 0
    while offset < MAX_ROWS:
        params = {
            "api-key": API_KEY, "format": "json",
            "limit": PAGE_SIZE, "offset": offset,
        }
        params.update(filters)
        data = api_get(params, show_url=(offset == 0))
        page = data.get("records", [])
        rows.extend(page)
        total = int(data.get("total", 0) or 0)
        print(f"  fetched {len(rows)} / {total} rows ...")
        if len(page) < PAGE_SIZE or len(rows) >= total:
            break
        offset += PAGE_SIZE
    return rows


def fetch_records():
    """Get every row for our state + district."""
    rows = fetch_all({
        "filters[state.keyword]": STATE,
        "filters[district]": DISTRICT,
    })
    # Fallback: if the district filter is too strict, fetch the whole state
    # and (a) tell the user which districts ARE reporting, (b) try to narrow
    # the district on our side.
    if not rows:
        print("No rows with the district filter -- retrying with state only ...")
        state_rows = fetch_all({"filters[state.keyword]": STATE})

        # Diagnostic: which districts in this state actually reported?
        from collections import Counter
        district_counts = Counter(
            get_field(r, "district", "District").strip()
            for r in state_rows
            if get_field(r, "district", "District").strip()
        )
        if district_counts:
            print(f"\nDistricts reporting in {STATE} (top 20 by row count):")
            for d, n in sorted(district_counts.items(),
                               key=lambda x: -x[1])[:20]:
                mark = "  <-- YOUR DISTRICT" if d.lower() == DISTRICT.lower() else ""
                print(f"  {d:<25} {n:>5} rows{mark}")
            if DISTRICT.lower() not in {d.lower() for d in district_counts}:
                print(f"\n  NOTE: '{DISTRICT}' is NOT in the list above, which "
                      f"means it didn't report today. Pick one of the names "
                      f"above and update DISTRICT in this file.\n")
        else:
            print(f"\nNo rows for {STATE} at all. Check the STATE spelling, "
                  f"your API key, and the network.\n")

        rows = [
            r for r in state_rows
            if get_field(r, "district", "District").strip().lower() == DISTRICT.lower()
        ]
    return rows

#Filter list for display only
def keep_our_crops(records):
    """Keep only the crops listed in CROPS (case-insensitive match)."""
    wanted = {c.lower() for c in CROPS}
    out = []
    for r in records:
        commodity = get_field(r, "Commodity", "commodity").strip()
        if commodity.lower() in wanted:
            out.append(r)
    return out


def print_table(records):
    """Print the results as a simple aligned table."""
    if not records:
        print("\nNo rows found for your crops in this district.")
        print("Tips: try a different DISTRICT, or check the CROPS spelling")
        print("against the names used on data.gov.in.")
        return

    header = f"{'Market':<22}{'Commodity':<22}{'Variety':<16}" \
             f"{'Min':>8}{'Modal':>9}{'Max':>9}  {'Arrival date':<14}"
    print("\n" + header)
    print("-" * len(header))

    dates = []
    for r in sorted(records, key=lambda x: get_field(x, "Commodity", "commodity")):
        market    = get_field(r, "Market", "market")
        commodity = get_field(r, "Commodity", "commodity")
        variety   = get_field(r, "Variety", "variety")
        min_p     = get_field(r, "Min_Price", "min_price")
        modal_p   = get_field(r, "Modal_Price", "modal_price")
        max_p     = get_field(r, "Max_Price", "max_price")
        arrival   = get_field(r, "Arrival_Date", "arrival_date")
        if arrival:
            dates.append(arrival)
        print(f"{market[:21]:<22}{commodity[:21]:<22}{variety[:15]:<16}"
              f"{min_p:>8}{modal_p:>9}{max_p:>9}  {arrival:<14}")

    # Data freshness summary -- this answers "how old is the data?"
    print("-" * len(header))
    if dates:
        newest = max(dates)
        print(f"DATA FRESHNESS: newest arrival date in the results is {newest}.")
        print("Compare that to today's date to see the real lag.")


def main():
    print(f"Fetching mandi prices for {DISTRICT}, {STATE} ...")
    records = fetch_records()
    print(f"API returned {len(records)} rows for the whole district.")

    # Save into the SQLite database so the price history grows over time.
    conn = init_db()
    saved = save_prices(conn, records)
    info  = db_summary(conn)
    print(f"Saved {saved} rows to mandi_prices.db  "
          f"(DB now has {info['total_rows']} rows; "
          f"newest arrival date: {info['newest_arrival_date']}).")

    ours = keep_our_crops(records)
    print(f"Of those, {len(ours)} rows match your {len(CROPS)} chosen crops.")
    print_table(ours)


if __name__ == "__main__":
    main()
