"""Stage E.1 -- Daily decision engine (proactive layer).

What this does
--------------
Runs ONCE per day (morning cron / Task Scheduler). For every registered
farmer it looks at:

    * their current stock       (crops on hand)
    * their open sell intents   (crops they plan to sell soon)
    * latest mandi prices       (from our SQLite database)
    * 7-day price forecast      (via best_window)
    * 3-day weather forecast    (via Open-Meteo)

and produces a structured list of NUDGES -- one per (farmer, trigger).
No LLM. Deterministic rules. Fully unit-testable.

The output feeds two later stages:
    Stage E.2 -- LLM turns each nudge into natural Hindi/Marathi text.
    Stage E.3 -- Telegram / WhatsApp bot actually sends the message.

Triggers implemented in this file
---------------------------------
    SELL_SIGNAL       -- best_window says action=='sell_today'.
    DEADLINE_WARNING  -- an open intent's deadline is within N days.
    WEATHER_BLOCK     -- safe_to_travel is not 'yes' today or tomorrow.

Output
------
    * returns list[dict] from decide_daily_advice()
    * writes daily_advice_YYYY-MM-DD.json for Stage E.2 to consume
    * prints a human-readable table for eyeballing

Run
---
    python daily_advice.py
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from db import init_db
from farmer_profile import list_stock
from open_intents import list_open_intents
from history_query import get_crop_history
from best_window import best_window
from weather import get_daily_forecast


# ---------------------------------------------------------------------------
# Tunable thresholds -- change these to make the engine more/less noisy
# ---------------------------------------------------------------------------
DEADLINE_WINDOW_DAYS = 3       # nudge if intent deadline is within this many days
WEATHER_CHECK_DAYS   = 2       # inspect today + tomorrow
MIN_HISTORY_DAYS     = 21      # skip SELL_SIGNAL if history is shorter than this


# ---------------------------------------------------------------------------
# Data type -- one row per nudge
# ---------------------------------------------------------------------------
@dataclass
class Nudge:
    farmer_phone: str
    farmer_name:  str
    farmer_village: str
    trigger:      str      # SELL_SIGNAL / DEADLINE_WARNING / WEATHER_BLOCK
    crop:         str      # empty string for weather (not crop-specific)
    urgency:      str      # high / medium / low
    reason:       str      # one-line English summary
    data:         dict     # supporting numbers so E.2 can format precisely


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _list_all_farmers(conn) -> list[dict]:
    """Every registered farmer with the fields we need for the engine."""
    rows = conn.execute(
        "SELECT phone, name, village, latitude, longitude, vehicle "
        "FROM farmers ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def _parse_iso_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _crops_of_interest(stock: list[dict], intents: list[dict]) -> set[str]:
    """Union of crops in stock + crops in open intents. That's what we care
    about for SELL_SIGNAL -- no point forecasting a crop the farmer doesn't
    own."""
    out: set[str] = set()
    for s in stock:
        c = (s.get("crop") or "").strip()
        if c:
            out.add(c)
    for i in intents:
        c = (i.get("crop") or "").strip()
        if c:
            out.add(c)
    return out


# ---------------------------------------------------------------------------
# Trigger 1: SELL_SIGNAL -- best_window says 'sell today'
# ---------------------------------------------------------------------------
def _check_sell_signal(farmer: dict, crop: str, conn) -> Optional[Nudge]:
    history = get_crop_history(conn, "Maharashtra", "Pune", crop)
    if not history or len(history) < MIN_HISTORY_DAYS:
        return None
    try:
        bw = best_window(history, days_ahead=7, model="holt_winters")
    except Exception:
        return None

    if bw.get("action") != "sell_today":
        return None

    todays = bw.get("todays_price")
    expected = bw.get("expected_price")
    conf = bw.get("confidence", "medium")

    reason = (
        f"Forecast says SELL TODAY: today's price ~Rs{todays:.0f}/q is at "
        f"the top of the 7-day window (best expected ~Rs{expected:.0f} on "
        f"{bw.get('best_day_date')})."
    )
    urgency = {"high": "high", "medium": "medium", "low": "low"}.get(conf, "medium")

    return Nudge(
        farmer_phone   = farmer["phone"],
        farmer_name    = farmer["name"],
        farmer_village = farmer.get("village") or "",
        trigger        = "SELL_SIGNAL",
        crop           = crop,
        urgency        = urgency,
        reason         = reason,
        data           = {
            "todays_price":     todays,
            "expected_price":   expected,
            "best_day_date":    bw.get("best_day_date"),
            "gain_vs_today":    bw.get("gain_vs_today"),
            "gain_vs_today_pct":bw.get("gain_vs_today_pct"),
            "confidence":       conf,
            "forecast":         bw.get("forecast"),
        },
    )


# ---------------------------------------------------------------------------
# Trigger 2: DEADLINE_WARNING -- an open intent's deadline is close
# ---------------------------------------------------------------------------
def _check_deadline_warning(farmer: dict, intents: list[dict],
                             today: date) -> list[Nudge]:
    out: list[Nudge] = []
    horizon = today + timedelta(days=DEADLINE_WINDOW_DAYS)
    for it in intents:
        d = _parse_iso_date(it.get("deadline"))
        if d is None:
            continue
        if not (today <= d <= horizon):
            continue

        days_left = (d - today).days
        urgency = "high" if days_left <= 1 else "medium"
        crop = it.get("crop") or ""
        qty = it.get("quantity_q")

        reason = (
            f"You planned to sell {crop} by {d.isoformat()} -- "
            f"only {days_left} day(s) left."
        )
        out.append(Nudge(
            farmer_phone   = farmer["phone"],
            farmer_name    = farmer["name"],
            farmer_village = farmer.get("village") or "",
            trigger        = "DEADLINE_WARNING",
            crop           = crop,
            urgency        = urgency,
            reason         = reason,
            data           = {
                "intent_id":  it.get("id"),
                "deadline":   d.isoformat(),
                "days_left":  days_left,
                "quantity_q": qty,
            },
        ))
    return out


# ---------------------------------------------------------------------------
# Trigger 3: WEATHER_BLOCK -- can't safely travel today or tomorrow
# ---------------------------------------------------------------------------
def _check_weather_block(farmer: dict,
                          forecast: list[dict]) -> Optional[Nudge]:
    """Emit AT MOST one weather nudge per farmer per day (the earliest
    unsafe day within the check window)."""
    if not forecast:
        return None
    for i, day in enumerate(forecast[:WEATHER_CHECK_DAYS]):
        flag = day.get("safe_to_travel")
        if flag == "yes":
            continue
        label = "TODAY" if i == 0 else f"on {day.get('date')}"
        # Urgency = severity (block vs warning) x when (today vs tomorrow).
        # 'no_*' flags are real blocks; 'caution_*' flags are warnings.
        is_block = flag in ("no_thunderstorm", "no_heavy_rain")
        if is_block:
            urgency = "high" if i == 0 else "medium"
        else:  # caution_rain / caution_heat
            urgency = "medium" if i == 0 else "low"
        weather_name = day.get("weather") or "unfavourable weather"
        precip = day.get("precipitation_mm") or 0
        reason = (
            f"Weather {label} looks bad for mandi travel: "
            f"{weather_name}, {precip} mm rain (flag={flag}). "
            f"Consider going a different day."
        )
        return Nudge(
            farmer_phone   = farmer["phone"],
            farmer_name    = farmer["name"],
            farmer_village = farmer.get("village") or "",
            trigger        = "WEATHER_BLOCK",
            crop           = "",
            urgency        = urgency,
            reason         = reason,
            data           = {"day": day},
        )
    return None


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------
def decide_daily_advice(today: Optional[date] = None,
                        write_json: bool = True,
                        verbose: bool = True) -> list[dict]:
    """Run the daily engine once. Returns the list of nudges as dicts.

    Optionally writes daily_advice_YYYY-MM-DD.json (Stage E.2 input) and
    prints a human-readable table.
    """
    today = today or date.today()
    conn = init_db()

    farmers = _list_all_farmers(conn)
    all_nudges: list[Nudge] = []

    for f in farmers:
        stock   = [dict(r) for r in list_stock(conn, f["phone"])]
        intents = list_open_intents(conn, phone=f["phone"])
        crops   = _crops_of_interest(stock, intents)

        # 1. Weather (one call per farmer -- location, not crop, dependent)
        try:
            forecast = get_daily_forecast(f["latitude"], f["longitude"],
                                          days=max(WEATHER_CHECK_DAYS, 3))
        except Exception:
            forecast = []
        wn = _check_weather_block(f, forecast)
        if wn is not None:
            all_nudges.append(wn)

        # 2. Deadline warnings (one per intent)
        for dn in _check_deadline_warning(f, intents, today):
            all_nudges.append(dn)

        # 3. Sell signals (one per crop of interest)
        for crop in sorted(crops):
            sn = _check_sell_signal(f, crop, conn)
            if sn is not None:
                all_nudges.append(sn)

    result = [asdict(n) for n in all_nudges]

    if write_json:
        path = f"daily_advice_{today.isoformat()}.json"
        with open(path, "w") as fh:
            json.dump({"date": today.isoformat(), "nudges": result}, fh, indent=2)

    if verbose:
        _print_report(today, result, farmers)

    return result


# ---------------------------------------------------------------------------
# Pretty printer -- easy on the eye when debugging
# ---------------------------------------------------------------------------
def _print_report(today: date, nudges: list[dict], farmers: list[dict]) -> None:
    print()
    print(f"===  Daily advice for {today.isoformat()}  ===")
    print(f"     farmers scanned : {len(farmers)}")
    print(f"     nudges produced : {len(nudges)}")
    print()

    if not nudges:
        print("  (no farmers need a nudge today)")
        return

    # Group by farmer for readability
    by_farmer: dict[str, list[dict]] = {}
    for n in nudges:
        by_farmer.setdefault(n["farmer_phone"], []).append(n)

    for phone, items in by_farmer.items():
        name = items[0]["farmer_name"]
        village = items[0]["farmer_village"]
        print(f"  -- {name} ({phone}, {village}) --")
        for n in items:
            crop_bit = f" [{n['crop']}]" if n["crop"] else ""
            print(f"     [{n['urgency'].upper():<6}] "
                  f"{n['trigger']:<18}{crop_bit}")
            print(f"              {n['reason']}")
        print()


if __name__ == "__main__":
    decide_daily_advice()
