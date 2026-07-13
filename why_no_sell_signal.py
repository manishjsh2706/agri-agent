"""Diagnostic: for every farmer's crops, show WHY SELL_SIGNAL didn't fire.

Answers one of two questions for each (farmer, crop):
    * "not enough history"   -> we need more days in the DB
    * "forecast says wait"   -> history is fine, but the model isn't seeing
                                today as the peak
    * "would fire"           -> and then it will actually appear in the JSON

Run:
    python why_no_sell_signal.py
"""

from db import init_db
from farmer_profile import list_stock
from open_intents import list_open_intents
from history_query import get_crop_history
from best_window import best_window
from daily_advice import MIN_HISTORY_DAYS


def _crops_for(conn, phone):
    crops = set()
    for s in list_stock(conn, phone):
        crops.add(dict(s)["crop"])
    for i in list_open_intents(conn, phone=phone):
        crops.add(i["crop"])
    return sorted(crops)


def main():
    conn = init_db()
    farmers = conn.execute(
        "SELECT phone, name FROM farmers ORDER BY name"
    ).fetchall()

    for f in farmers:
        phone, name = f["phone"], f["name"]
        crops = _crops_for(conn, phone)
        if not crops:
            print(f"-- {name} ({phone}): no stock or intents, skipping")
            continue
        print(f"-- {name} ({phone}):")
        for crop in crops:
            history = get_crop_history(conn, "Maharashtra", "Pune", crop)
            n = len(history) if history else 0
            if n < MIN_HISTORY_DAYS:
                print(f"    {crop:<12} {n:>3} days of history "
                      f"(need >= {MIN_HISTORY_DAYS}). BLOCKED: not enough data.")
                continue
            try:
                bw = best_window(history, days_ahead=7, model="holt_winters")
            except Exception as e:
                print(f"    {crop:<12} {n:>3} days, but best_window failed: {e}")
                continue
            action = bw.get("action")
            today = bw.get("todays_price")
            expected = bw.get("expected_price")
            peak_day = bw.get("best_day_date")
            if action == "sell_today":
                verdict = "WOULD FIRE (SELL_SIGNAL will appear in JSON)"
            else:
                verdict = (f"forecast says '{action}': "
                           f"peak Rs{expected} on {peak_day} vs "
                           f"today Rs{today}")
            print(f"    {crop:<12} {n:>3} days, action={action:<11} {verdict}")
        print()


if __name__ == "__main__":
    main()
