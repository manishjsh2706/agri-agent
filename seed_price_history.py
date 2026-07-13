"""One-shot: seed 40 days of REALISTIC price history that ENDS YESTERDAY.

Why this exists
---------------
best_window() needs >= 21 days of history to forecast. Your real fetch
has only been running a week, and mock_history.real_world_mix() has TWO
issues that make it unsuitable as-is:

    1. _dates() defaults to end=date(2026,6,21) -- always ends 2+ weeks
       ago, so best_window thinks "today" is stale.
    2. real_world_mix() has a rising drift, so today is never the peak
       and best_window always returns action='wait'. SELL_SIGNAL never
       fires.

This script generates history INLINE with dates ending yesterday and
THREE deliberately different price shapes, so you see all three
best_window verdicts (sell_today / wait / indifferent) in one run.

    Onion  -- linear FALLING  -> action=sell_today  (SELL_SIGNAL fires)
    Tomato -- flat with noise -> action=indifferent (no signal)
    Wheat  -- linear RISING   -> action=wait        (no signal)

Real fetched rows for TODAY are NOT touched (last synthetic row is
yesterday's), so your Task Scheduler keeps writing real prices for today.

Run:
    python seed_price_history.py
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from db import init_db


DAYS = 40   # 21 min for best_window; 40 gives Holt-Winters room to breathe


def _dates_ending_yesterday(n_days: int) -> list[str]:
    """n_days DD/MM/YYYY strings, oldest first, LAST one = yesterday."""
    end = date.today() - timedelta(days=1)
    return [(end - timedelta(days=n_days - 1 - i)).strftime("%d/%m/%Y")
            for i in range(n_days)]


def _linear(start: float, end_val: float, days: int, noise: float,
             seed: int) -> list[float]:
    rng = random.Random(seed)
    step = (end_val - start) / max(days - 1, 1)
    return [start + step * i + rng.gauss(0, noise) for i in range(days)]


def _flat(price: float, days: int, noise: float, seed: int) -> list[float]:
    rng = random.Random(seed)
    return [price + rng.gauss(0, noise) for _ in range(days)]


# (market, commodity, price-generator lambda) -- each lambda returns the
# list of prices oldest-first.
SEEDS = [
    ("Pune",         "Onion",
     lambda: _linear(start=3000, end_val=2200, days=DAYS, noise=25, seed=101)),
    ("Pune(Manjri)", "Tomato",
     lambda: _flat(price=1800, days=DAYS, noise=40, seed=102)),
    ("Chakan",       "Wheat",
     lambda: _linear(start=2000, end_val=2400, days=DAYS, noise=25, seed=103)),
]


def _to_row(state, district, market, commodity, date_str, price):
    modal = float(price)
    return (
        state, district, market, commodity,
        "Local", "FAQ",
        date_str,
        round(modal * 0.90, 2),
        round(modal,        2),
        round(modal * 1.10, 2),
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def main() -> None:
    conn = init_db()
    dates = _dates_ending_yesterday(DAYS)
    total = 0
    for market, crop, gen in SEEDS:
        prices = gen()
        rows = [
            _to_row("Maharashtra", "Pune", market, crop, d, p)
            for d, p in zip(dates, prices)
        ]
        conn.executemany(
            """
            INSERT OR REPLACE INTO prices
                (state, district, market, commodity, variety, grade,
                 arrival_date, min_price, modal_price, max_price, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        first, last = dates[0], dates[-1]
        print(f"  seeded {len(rows):>3} rows  {crop:<8} @ {market:<14} "
              f"{first} -> {last}  (modal Rs{prices[0]:.0f} -> Rs{prices[-1]:.0f})")
        total += len(rows)

    print()
    print(f"Total {total} rows written.")
    print("Now:")
    print("  1. python why_no_sell_signal.py   # Onion should show action=sell_today")
    print("  2. python daily_advice.py         # SELL_SIGNAL nudge should appear for Onion")


if __name__ == "__main__":
    main()
