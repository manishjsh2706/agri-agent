"""Verify where Rs1900/q for Onion came from.

Shows:
  1. Every mandi's Onion modal_price for TODAY (or newest available date)
  2. The median across those mandis -- which is what best_window uses
  3. What history_query.get_crop_history() returned for the last 7 days

Run with:  python verify_onion_price.py
"""

from datetime import date
from db import init_db
from history_query import get_crop_history, _median


def _pretty_date(iso_or_dmy):
    return iso_or_dmy   # just show whatever the DB stores


def main():
    conn = init_db()
    CROP = "Onion"

    # 1. Every mandi's Onion price on the most recent date they reported.
    print(f"=== Every mandi's {CROP} rate (newest report per mandi) ===")
    rows = conn.execute(
        """
        SELECT market, modal_price, min_price, max_price, arrival_date
          FROM prices
         WHERE state='Maharashtra' AND district='Pune'
           AND LOWER(commodity)=LOWER(?)
           AND modal_price IS NOT NULL AND modal_price > 0
         ORDER BY market, arrival_date DESC
        """,
        (CROP,),
    ).fetchall()

    # keep only newest row per market
    latest = {}
    for r in rows:
        m = r["market"]
        if m not in latest:
            latest[m] = dict(r)

    prices_today = []
    print(f"{'market':<24}{'modal':>10}{'min':>10}{'max':>10}  {'as of'}")
    for r in sorted(latest.values(), key=lambda x: x["market"]):
        print(f"{r['market']:<24}{r['modal_price']:>10.0f}"
              f"{r['min_price'] or 0:>10.0f}{r['max_price'] or 0:>10.0f}"
              f"  {r['arrival_date']}")
        prices_today.append(r["modal_price"])

    if prices_today:
        median_today = _median([float(p) for p in prices_today])
        print(f"\n  MEDIAN across {len(prices_today)} mandis: "
              f"Rs{median_today:.0f}/q")
        print(f"  (this is roughly what best_window used as todays_price)")

    # 2. What history_query returned for the last 7 days
    print()
    print(f"=== history_query.get_crop_history() -- last 7 days ===")
    history = get_crop_history(conn, "Maharashtra", "Pune", CROP)
    for d, p in history[-7:]:
        marker = "  <-- today's median (todays_price)" if (d, p) == history[-1] else ""
        print(f"  {d}   Rs{p:.0f}/q{marker}")

    print()
    print("If Rs1900 in your Telegram matches the last row above, that's")
    print("where it came from -- median of Pune-district Onion prices.")


if __name__ == "__main__":
    main()
