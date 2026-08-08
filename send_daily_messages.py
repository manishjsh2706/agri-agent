"""Stage E.3b -- send the day's advice messages via Telegram.

Runs ONCE per day (after advice_writer.py). For each entry in
daily_messages_YYYY-MM-DD.json:

    * look up the farmer's telegram_chat_id in the DB
    * if registered -> Telegram API sendMessage
    * if not registered -> log a skip

Report at the end:  N sent, M skipped, K errored.

Wire this into your morning Task Scheduler chain AFTER advice_writer.py:

    fetch_prices  ->  daily_advice  ->  advice_writer  ->  send_daily_messages

Optional argument: pass a specific date.

    python send_daily_messages.py                # today
    python send_daily_messages.py 2026-07-05     # a specific day
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")

from db import init_db


TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not TOKEN:
    sys.exit("TELEGRAM_BOT_TOKEN is missing in your environment / .env file.")

API = f"https://api.telegram.org/bot{TOKEN}"


def _load_messages(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload.get("messages", []) or []


def _chat_id_for_phone(conn, phone: str) -> Optional[int]:
    row = conn.execute(
        "SELECT telegram_chat_id FROM farmers WHERE phone = ?",
        (phone,),
    ).fetchone()
    if not row:
        return None
    val = row["telegram_chat_id"]
    return int(val) if val else None


def _send(chat_id: int, text: str) -> tuple[bool, str]:
    try:
        r = requests.post(
            f"{API}/sendMessage",
            data={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        if r.status_code == 200 and r.json().get("ok"):
            return True, "OK"
        return False, f"http={r.status_code} body={r.text[:200]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def send_all(today: Optional[date] = None,
             messages_path: Optional[str] = None) -> dict:
    today = today or date.today()
    mode = os.environ.get("BRIEFING_MODE", "morning")
    messages_path = messages_path or f"daily_messages_{today.isoformat()}_{mode}.json"

    messages = _load_messages(messages_path)
    if not messages:
        print(f"No messages in {messages_path}. Nothing to send.")
        return {"sent": 0, "skipped": 0, "errored": 0}

    conn = init_db()
    sent = skipped = errored = 0

    print(f"Sending {len(messages)} message(s) for {today.isoformat()}...")
    print()

    for m in messages:
        name = m.get("name") or "(unknown)"
        phone = m.get("phone") or ""
        text = (m.get("message") or "").strip()
        if not text:
            print(f"  [SKIP]   {name:<18} ({phone})  empty message body")
            skipped += 1
            continue

        chat_id = _chat_id_for_phone(conn, phone)
        if not chat_id:
            print(f"  [SKIP]   {name:<18} ({phone})  no Telegram registration")
            skipped += 1
            continue

        ok, detail = _send(chat_id, text)
        if ok:
            print(f"  [SENT]   {name:<18} ({phone})  chat={chat_id}")
            sent += 1
        else:
            print(f"  [ERROR]  {name:<18} ({phone})  {detail}")
            errored += 1

    print()
    print(f"Summary: sent={sent}  skipped={skipped}  errored={errored}")
    return {"sent": sent, "skipped": skipped, "errored": errored}


if __name__ == "__main__":
    d = None
    if len(sys.argv) > 1:
        try:
            d = date.fromisoformat(sys.argv[1])
        except ValueError:
            print("usage: python send_daily_messages.py [YYYY-MM-DD]")
            sys.exit(1)
    send_all(today=d)
