"""Pull a crop's daily price time series from mandi_prices.db.

Given a state, district, and commodity, returns a list of
(date_string, modal_price) tuples, oldest-first, aggregated across
every mandi that reported that day.

We use the MEDIAN modal price per day (across all mandis reporting
the crop). Median is robust to a single mandi's outlier (bad row,
special variety, etc.), while still tracking the district's real
market level.

Public function
---------------
    get_crop_history(conn, state, district, crop) -> list[(date, price)]
"""

import sqlite3
from datetime import datetime


def _parse_date(s: str):
    return datetime.strptime(s.strip(), "%d/%m/%Y").date()


def _median(values: list[float]) -> float:
    xs = sorted(values)
    n = len(xs)
    if n == 0:
        return 0.0
    if n % 2 == 1:
        return xs[n // 2]
    return 0.5 * (xs[n // 2 - 1] + xs[n // 2])


def get_crop_history(
    conn: sqlite3.Connection,
    state: str = "Maharashtra",
    district: str = "Pune",
    crop: str = "Onion",
) -> list[tuple[str, float]]:
    """Return median modal price per day for a crop, oldest-first."""
    rows = conn.execute(
        """
        SELECT arrival_date, modal_price
          FROM prices
         WHERE state = ?
           AND district = ?
           AND LOWER(commodity) = LOWER(?)
           AND modal_price IS NOT NULL
           AND modal_price > 0
        """,
        (state, district, crop),
    ).fetchall()

    by_date: dict[str, list[float]] = {}
    for r in rows:
        # rows might be sqlite3.Row (with keys) or plain tuple
        date_str = r["arrival_date"] if hasattr(r, "keys") else r[0]
        price    = r["modal_price"]  if hasattr(r, "keys") else r[1]
        by_date.setdefault(date_str, []).append(float(price))

    history: list[tuple[str, float]] = [
        (d, round(_median(ps), 2)) for d, ps in by_date.items()
    ]
    history.sort(key=lambda x: _parse_date(x[0]))
    return history
