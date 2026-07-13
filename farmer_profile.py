"""Farmer profile and stock helpers (Stage B.4).

Public functions
----------------
    get_farmer(conn, phone)            -> dict or None
    save_farmer(conn, phone, name, ...) -> dict (the upserted row)
    list_farmers(conn)                 -> list of dicts
    set_stock(conn, phone, crop, quantity_q, ...) -> int (the new stock id)
    list_stock(conn, phone, status='available') -> list of dicts
    mark_sold(conn, phone, crop)       -> count of rows updated

Phone numbers are the unique identifier. We store them as plain text so
international formats (e.g. '+919876543210') work the same as local
formats. Callers should normalise (strip spaces, dashes) before saving.
"""

import sqlite3
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalise_phone(phone: str) -> str:
    """Strip spaces, dashes and parentheses; collapse to a clean number."""
    if phone is None:
        return ""
    return "".join(ch for ch in str(phone) if ch.isdigit() or ch == "+")


# ---------------------------------------------------------------------------
# Farmer CRUD
# ---------------------------------------------------------------------------
def get_farmer(conn: sqlite3.Connection, phone: str) -> dict | None:
    """Return the farmer dict for this phone number, or None if not found."""
    phone = _normalise_phone(phone)
    if not phone:
        return None
    row = conn.execute(
        "SELECT * FROM farmers WHERE phone = ?", (phone,)
    ).fetchone()
    return dict(row) if row else None


def save_farmer(
    conn: sqlite3.Connection,
    phone: str,
    name: str,
    latitude: float,
    longitude: float,
    vehicle: str,
    *,
    village: str = "",
    crops: str = "",
    language: str = "en",
) -> dict:
    """Insert a new farmer or update an existing one (upsert by phone)."""
    phone = _normalise_phone(phone)
    if not phone:
        raise ValueError("phone is required")
    if not name:
        raise ValueError("name is required")
    if vehicle not in {"tractor_trolley", "mini_truck", "truck"}:
        raise ValueError(
            f"unknown vehicle '{vehicle}'; "
            f"use tractor_trolley, mini_truck or truck"
        )

    now = _now()
    existing = get_farmer(conn, phone)
    if existing:
        conn.execute(
            """
            UPDATE farmers
               SET name=?, village=?, latitude=?, longitude=?,
                   vehicle=?, crops=?, language=?, updated_at=?
             WHERE phone=?
            """,
            (name, village, latitude, longitude, vehicle, crops,
             language, now, phone),
        )
    else:
        conn.execute(
            """
            INSERT INTO farmers
                (phone, name, village, latitude, longitude,
                 vehicle, crops, language, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (phone, name, village, latitude, longitude, vehicle,
             crops, language, now, now),
        )
    conn.commit()
    return get_farmer(conn, phone)


def list_farmers(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM farmers ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Stock CRUD
# ---------------------------------------------------------------------------
def set_stock(
    conn: sqlite3.Connection,
    phone: str,
    crop: str,
    quantity_q: float,
    *,
    harvested_on: str = "",
    notes: str = "",
) -> int:
    """Add a new stock entry for a farmer. Returns the new row id."""
    phone = _normalise_phone(phone)
    if not get_farmer(conn, phone):
        raise ValueError(f"no farmer registered for phone '{phone}'")
    if not crop:
        raise ValueError("crop is required")
    if quantity_q <= 0:
        raise ValueError("quantity must be positive")

    now = _now()
    cur = conn.execute(
        """
        INSERT INTO stock
            (phone, crop, quantity_q, harvested_on, status,
             notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'available', ?, ?, ?)
        """,
        (phone, crop, quantity_q, harvested_on, notes, now, now),
    )
    conn.commit()
    return cur.lastrowid


def list_stock(
    conn: sqlite3.Connection,
    phone: str,
    status: str = "available",
) -> list[dict]:
    """List stock for a farmer; default is only 'available' rows."""
    phone = _normalise_phone(phone)
    rows = conn.execute(
        """
        SELECT * FROM stock
         WHERE phone = ? AND status = ?
         ORDER BY harvested_on DESC, id DESC
        """,
        (phone, status),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_sold(
    conn: sqlite3.Connection,
    phone: str,
    crop: str,
) -> int:
    """Mark all 'available' stock for this farmer + crop as sold.
    Returns the number of rows updated."""
    phone = _normalise_phone(phone)
    now = _now()
    cur = conn.execute(
        """
        UPDATE stock
           SET status = 'sold', updated_at = ?
         WHERE phone = ? AND LOWER(crop) = LOWER(?) AND status = 'available'
        """,
        (now, phone, crop),
    )
    conn.commit()
    return cur.rowcount
