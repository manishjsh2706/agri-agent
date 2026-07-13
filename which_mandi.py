"""Live query: 'which mandi should the farmer go to today?'

Reads the most recent prices from mandi_prices.db (populated by
fetch_mandi_prices.py), looks up Pune mandi coordinates from
pune_mandis.py, and runs everything through the comparison engine.
Prints a farmer-friendly recommendation.

Run with:

    python which_mandi.py
"""

from db import init_db
from comparison import compare_mandis
from pune_mandis import PUNE_MANDIS


# ----------------------------------------------------------------------
# FARMER QUERY  --  edit these values to try different situations
# ----------------------------------------------------------------------
FARMER = {
    "name":    "Test farmer",
    "lat":     18.5800,#18.5089,        # near Pune APMC
    "lon":     73.9692,#73.9259,
    "vehicle": "mini_truck",   # tractor_trolley | mini_truck | truck
}
CROP              = "Onion"
QUANTITY_QUINTALS = 10
RADIUS_KM         = 60         # Pune district is large; 60 km covers most of it
# ----------------------------------------------------------------------


def fetch_latest_for_crop(conn, state, district, crop):
    """Return every price row for the crop in this district, newest first."""
    rows = conn.execute(
        """
        SELECT market, commodity, variety, grade,
               min_price, modal_price, max_price, arrival_date
          FROM prices
         WHERE state = ?
           AND district = ?
           AND LOWER(commodity) = LOWER(?)
        """,
        (state, district, crop),
    ).fetchall()
    return [dict(r) for r in rows]


def main():
    conn = init_db()
    rows = fetch_latest_for_crop(conn, "Maharashtra", "Pune", CROP)

    if not rows:
        print(f"No rows for '{CROP}' in Pune in the database.")
        print("Tips:")
        print("  - run `python fetch_mandi_prices.py` to refresh the database")
        print("  - check the spelling of CROP at the top of this file against "
              "the Commodity column in the database")
        return

    print(f"Found {len(rows)} rows for '{CROP}' in Pune.")

    # Diagnostic: any markets in the data without coordinates?
    known = set(PUNE_MANDIS.keys())
    seen  = {r["market"] for r in rows}
    missing = sorted(seen - known)
    if missing:
        print("\nNote: these market names appear in the data but have no "
              "coordinates yet:")
        for m in missing:
            print(f"  - {m}")
        print("Add them to pune_mandis.py for the engine to consider them.\n")

    result = compare_mandis(
        prices=rows,
        mandi_locations=PUNE_MANDIS,
        farmer_lat=FARMER["lat"],
        farmer_lon=FARMER["lon"],
        vehicle=FARMER["vehicle"],
        crop=CROP,
        radius_km=RADIUS_KM,
        quantity_quintals=QUANTITY_QUINTALS,
    )

    if result["no_data_for_crop"]:
        print(f"\nThe engine reported no rows for '{CROP}'. "
              f"(Spelling? Try the exact value from the data.)")
        return

    if not result["ranking"]:
        print(f"\nNo mandis within {RADIUS_KM} km had usable prices.")
        if result["excluded_for_radius"]:
            print(f"  Excluded for radius: {result['excluded_for_radius']}")
        if result["bad_rows_skipped"]:
            print(f"  Bad rows skipped:    {result['bad_rows_skipped']}")
        return

    print()
    print(f"Recommendation for {FARMER['name']} "
          f"(vehicle: {FARMER['vehicle']}, {QUANTITY_QUINTALS} q of {CROP}):")
    print()
    print(f"  {'Rank':<5}{'Mandi':<24}{'Distance':>10}{'Modal':>9}"
          f"{'Transport/q':>13}{'Net/q':>9}{'As of':>14}")
    print("  " + "-" * 80)
    for i, it in enumerate(result["ranking"], 1):
        mark = " *" if it["is_stale"] else ""
        print(f"  {i:<5}{it['market']:<24}"
              f"{it['distance_km']:>8.1f} km"
              f"{it['gross_modal_price']:>9.0f}"
              f"{it['transport_cost_per_quintal']:>13.0f}"
              f"{it['net_price_per_quintal']:>9.0f}"
              f"{it['arrival_date']:>14}{mark}")
    print()
    top = result["ranking"][0]
    print(f"  BEST: Go to {result['top_mandi']} -- about "
          f"Rs {top['net_price_per_quintal']:.0f}/quintal after transport "
          f"(gross Rs {top['gross_modal_price']:.0f}, "
          f"transport Rs {top['transport_cost_per_quintal']:.0f}/q over "
          f"{top['distance_km']:.0f} km).")

    if result["low_confidence"]:
        print()
        print("  WARNING: every nearby mandi reported more than 2 days ago; "
              "treat the result as low confidence.")
    elif result["freshness_warning_for"]:
        print()
        print(f"  Note: data for {result['freshness_warning_for']} is older "
              f"than 2 days (marked with * above).")

    if result["excluded_for_radius"]:
        print()
        print(f"  Mandis excluded for being outside {RADIUS_KM} km: "
              f"{result['excluded_for_radius']}")


if __name__ == "__main__":
    main()
