"""SQLite storage for daily mandi prices.

WHAT THIS GIVES YOU
-------------------
  * A single file (mandi_prices.db) that grows day by day.
  * Re-running the fetch script for the same day does NOT duplicate rows.
  * Every later step (comparison engine, forecast, etc.) reads from
    this file rather than calling the API again and again.

PUBLIC HELPERS
--------------
  init_db(path)            -- open/create the database, return a connection
  save_prices(conn, recs)  -- upsert a batch of API records, returns count
  db_summary(conn)         -- {"total_rows": N, "newest_arrival_date": "..."}
  latest_prices(conn, state, district, commodity)
                           -- list of dicts with the most recent prices

You can also run this file directly for a quick self-test:

    python db.py
"""

import os
import sqlite3
from datetime import datetime, timezone

DEFAULT_DB_PATH = "mandi_prices.db"


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------
def init_db(path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open the SQLite database at `path`, creating the table if missing."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row  # rows behave like dicts when queried

    # The composite primary key prevents duplicates when the same
    # (market + commodity + variety + grade) reports the same arrival_date
    # more than once -- INSERT OR REPLACE just updates the existing row.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prices (
            state         TEXT NOT NULL,
            district      TEXT NOT NULL,
            market        TEXT NOT NULL,
            commodity     TEXT NOT NULL,
            variety       TEXT NOT NULL,
            grade         TEXT NOT NULL,
            arrival_date  TEXT NOT NULL,
            min_price     REAL,
            modal_price   REAL,
            max_price     REAL,
            fetched_at    TEXT NOT NULL,
            PRIMARY KEY (state, district, market, commodity,
                         variety, grade, arrival_date)
        )
        """
    )
    # Helpful indexes for the queries we'll run later.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_prices_lookup "
        "ON prices(state, district, commodity, arrival_date)"
    )

    # --- Stage B.4: farmer profile store --------------------------------
    # One row per farmer. Phone number is the unique identifier so the
    # same row works when we move to Telegram / WhatsApp later.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS farmers (
            phone        TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            village      TEXT,
            latitude     REAL NOT NULL,
            longitude    REAL NOT NULL,
            vehicle      TEXT NOT NULL,
            crops        TEXT,
            language     TEXT DEFAULT 'en',
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        )
        """
    )
    # One row per (farmer, crop, batch) of produce in stock. Status moves
    # from 'available' -> 'sold' (or 'expired') as the farmer reports.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stock (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            phone         TEXT NOT NULL,
            crop          TEXT NOT NULL,
            quantity_q    REAL NOT NULL,
            harvested_on  TEXT,
            status        TEXT NOT NULL DEFAULT 'available',
            notes         TEXT,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            FOREIGN KEY (phone) REFERENCES farmers(phone)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_stock_phone "
        "ON stock(phone, status)"
    )

    # --- Stage D.5: open intents (things farmers PLAN to do) ------------
    # Each row = one thing a farmer wants to do but hasn't done yet.
    # status moves from 'open' -> 'fulfilled' | 'cancelled' | 'expired'.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS open_intents (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            phone         TEXT NOT NULL,
            intent_type   TEXT NOT NULL DEFAULT 'sell',
            crop          TEXT NOT NULL,
            quantity_q    REAL,
            deadline      TEXT,     -- ISO date YYYY-MM-DD (optional)
            notes         TEXT,
            status        TEXT NOT NULL DEFAULT 'open',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            FOREIGN KEY (phone) REFERENCES farmers(phone)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_open_intents_phone "
        "ON open_intents(phone, status)"
    )

    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------
def _get(record: dict, *keys: str) -> str:
    """Return the first non-empty value among keys (case-insensitive aliases)."""
    for k in keys:
        if k in record and record[k] not in (None, ""):
            return record[k]
    return ""


def _to_float(value) -> float | None:
    """Best-effort float conversion; returns None if not a number."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def save_prices(conn: sqlite3.Connection, records: list[dict]) -> int:
    """Upsert a batch of API records. Returns how many rows were written."""
    if not records:
        return 0

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    rows = []
    for r in records:
        rows.append(
            (
                _get(r, "state", "State"),
                _get(r, "district", "District"),
                _get(r, "market", "Market"),
                _get(r, "commodity", "Commodity"),
                _get(r, "variety", "Variety"),
                _get(r, "grade", "Grade"),
                _get(r, "arrival_date", "Arrival_Date"),
                _to_float(_get(r, "min_price", "Min_Price")),
                _to_float(_get(r, "modal_price", "Modal_Price")),
                _to_float(_get(r, "max_price", "Max_Price")),
                fetched_at,
            )
        )

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
    return len(rows)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------
def db_summary(conn: sqlite3.Connection) -> dict:
    """Return a short summary of what's in the database."""
    cur = conn.execute(
        "SELECT COUNT(*) AS total, MAX(arrival_date) AS newest FROM prices"
    )
    row = cur.fetchone()
    return {
        "total_rows": row["total"] or 0,
        "newest_arrival_date": row["newest"] or "(none)",
    }


def latest_prices(
    conn: sqlite3.Connection,
    state: str,
    district: str,
    commodity: str,
) -> list[dict]:
    """Return the most recent price per market for a given crop and district."""
    cur = conn.execute(
        """
        SELECT market, commodity, variety, grade,
               min_price, modal_price, max_price,
               arrival_date
          FROM prices
         WHERE state = ? AND district = ? AND commodity = ?
         ORDER BY market, arrival_date DESC
        """,
        (state, district, commodity),
    )
    rows = [dict(r) for r in cur.fetchall()]
    # Keep only the newest row per market (rows are already sorted desc by date)
    seen = set()
    latest = []
    for r in rows:
        if r["market"] not in seen:
            latest.append(r)
            seen.add(r["market"])
    return latest


# ---------------------------------------------------------------------------
# Self-test: `python db.py`
# ---------------------------------------------------------------------------
def _self_test() -> None:
    test_path = "_db_selftest.db"
    if os.path.exists(test_path):
        os.remove(test_path)

    conn = init_db(test_path)

    # Two fake API records, then re-save the second one to confirm upsert.
    sample = [
        {
            "state": "Maharashtra", "district": "Nagpur",
            "market": "Nagpur", "commodity": "Onion", "variety": "Local",
            "grade": "FAQ", "arrival_date": "24/05/2026",
            "min_price": 2100, "modal_price": 2300, "max_price": 2500,
        },
        {
            "state": "Maharashtra", "district": "Nagpur",
            "market": "Kamptee", "commodity": "Onion", "variety": "Local",
            "grade": "FAQ", "arrival_date": "24/05/2026",
            "min_price": 2000, "modal_price": 2200, "max_price": 2400,
        },
    ]
    save_prices(conn, sample)
    sample[1]["modal_price"] = 2250
    save_prices(conn, sample)
    print("Self-test:", db_summary(conn))
    print("Latest prices for Onion in Nagpur:")
    for r in latest_prices(conn, "Maharashtra", "Nagpur", "Onion"):
        print(f"  {r['market']:<10} modal={r['modal_price']}  ({r['arrival_date']})")
    conn.close()
    os.remove(test_path)
    print("OK.")


if __name__ == "__main__":
    _self_test()
