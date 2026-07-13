"""Stage D.5 -- helpers for the open_intents table.

WHY THIS FILE EXISTS
--------------------
The chat's short-term memory (Stage D.4) forgets past conversations
between sessions. This module gives us LONG-TERM, structured memory
of pending farmer intents like "Manish wants to sell 20q onions by
next Friday". Once written, that record survives restarts and can be
scanned by Stage E's daily job to send proactive advice.

PUBLIC FUNCTIONS
----------------
    create_intent(conn, phone, crop, quantity_q=None, deadline=None, notes="")
        -> returns the new intent's id.
    list_open_intents(conn, phone=None) -> list of dicts
    mark_fulfilled(conn, intent_id)   -> count of rows updated
    mark_cancelled(conn, intent_id)   -> count of rows updated
    expire_stale(conn, older_than_days=30)
        -> auto-close intents that are older than N days and still open.

Every function is a thin, safe wrapper around a single SQL statement so
the LLM tools can call them without worrying about SQL injection or edge
cases.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta


# --- helpers ---------------------------------------------------------------
def _now() -> str:
    """UTC timestamp string, e.g. '2026-06-21T09:15:32+00:00'."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalise_phone(phone: str) -> str:
    """Strip spaces / dashes so different formats of the same phone match."""
    return "".join(c for c in str(phone or "") if c.isdigit() or c == "+")


# --- CREATE ----------------------------------------------------------------
def create_intent(
    conn: sqlite3.Connection,
    phone: str,
    crop: str,
    quantity_q: float | None = None,
    deadline: str | None = None,          # ISO YYYY-MM-DD
    notes: str = "",
    intent_type: str = "sell",
) -> int:
    """Write a new pending intent. Returns the row id."""
    phone = _normalise_phone(phone)
    if not phone:
        raise ValueError("phone is required")
    if not crop:
        raise ValueError("crop is required")

    now = _now()
    cur = conn.execute(
        """
        INSERT INTO open_intents
            (phone, intent_type, crop, quantity_q, deadline, notes,
             status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?)
        """,
        (phone, intent_type, crop, quantity_q, deadline, notes, now, now),
    )
    conn.commit()
    return cur.lastrowid


# --- READ ------------------------------------------------------------------
def list_open_intents(
    conn: sqlite3.Connection,
    phone: str | None = None,
) -> list[dict]:
    """List every 'open' intent. If phone is given, only that farmer's."""
    if phone:
        rows = conn.execute(
            "SELECT * FROM open_intents WHERE phone = ? AND status = 'open' "
            "ORDER BY created_at DESC",
            (_normalise_phone(phone),),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM open_intents WHERE status = 'open' "
            "ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# --- UPDATE ----------------------------------------------------------------
def _set_status(conn, intent_id: int, new_status: str) -> int:
    """Internal helper -- move an intent to a new status."""
    cur = conn.execute(
        "UPDATE open_intents SET status = ?, updated_at = ? "
        "WHERE id = ? AND status = 'open'",
        (new_status, _now(), intent_id),
    )
    conn.commit()
    return cur.rowcount


def mark_fulfilled(conn: sqlite3.Connection, intent_id: int) -> int:
    """Farmer actually sold the produce -> close the intent."""
    return _set_status(conn, intent_id, "fulfilled")


def mark_cancelled(conn: sqlite3.Connection, intent_id: int) -> int:
    """Farmer changed their mind or the intent no longer applies."""
    return _set_status(conn, intent_id, "cancelled")


# --- EXPIRE ----------------------------------------------------------------
def expire_stale(
    conn: sqlite3.Connection,
    older_than_days: int = 30,
) -> int:
    """Auto-close any intent still 'open' after N days.
    Prevents the table from filling with abandoned plans."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)) \
        .isoformat(timespec="seconds")
    cur = conn.execute(
        "UPDATE open_intents SET status = 'expired', updated_at = ? "
        "WHERE status = 'open' AND created_at < ?",
        (_now(), cutoff),
    )
    conn.commit()
    return cur.rowcount
