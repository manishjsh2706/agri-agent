"""Stage E.3a -- registration bot + two-way conversational agent.

Handles four SLASH commands (registration lifecycle) AND forwards every
free-form message to the LangGraph agent (agent_memory.py) so farmers
can ask questions like:

    "what is my stock?"
    "which mandi is best for onion?"
    "should i go to the mandi today?"
    "मेरा तमाटर कितना है?"

The bot infers the farmer from the Telegram chat_id -> phone mapping
we set up during /register, then calls ask_agent_with_memory() with
their phone (as thread_id) and language (from the farmers table).

Setup
-----
1. In Telegram, message @BotFather:  /newbot -> get a bot token
2. Put TELEGRAM_BOT_TOKEN=... in your .env
3. python add_telegram_column.py     # one-time migration
4. python telegram_bot.py            # start listening

Commands
--------
    /start                -- greet
    /register <phone>     -- link this chat to a farmer
    /whoami               -- show current registration
    /unregister           -- unlink
    (anything else)       -- forwarded to the LangGraph agent
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")

from db import init_db

# Import the agent lazily inside the handler so a missing OpenAI key
# doesn't crash the bot at import time (registration should still work).


TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not TOKEN:
    sys.exit("TELEGRAM_BOT_TOKEN is missing in your environment / .env file.")

API = f"https://api.telegram.org/bot{TOKEN}"

# Telegram hard-limits sendMessage bodies to 4096 chars; leave room for safety.
TELEGRAM_MAX_CHARS = 4000


# ---------------------------------------------------------------------------
# Telegram helpers
# ---------------------------------------------------------------------------
def _get_updates(offset, timeout=25):
    params = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    try:
        r = requests.get(f"{API}/getUpdates", params=params,
                         timeout=timeout + 5)
        r.raise_for_status()
        return r.json().get("result", []) or []
    except Exception as e:
        print(f"  getUpdates error: {type(e).__name__}: {e}")
        return []


def _send_message(chat_id, text):
    if not text:
        return
    if len(text) > TELEGRAM_MAX_CHARS:
        text = text[:TELEGRAM_MAX_CHARS - 20] + "\n[...truncated]"
    try:
        requests.post(f"{API}/sendMessage",
                      data={"chat_id": chat_id, "text": text},
                      timeout=20)
    except Exception as e:
        print(f"  sendMessage error: {type(e).__name__}: {e}")


def _send_typing(chat_id):
    """Show 'typing...' while the LLM works. Best-effort."""
    try:
        requests.post(f"{API}/sendChatAction",
                      data={"chat_id": chat_id, "action": "typing"},
                      timeout=10)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _normalise_phone(s):
    return "".join(c for c in (s or "") if c.isdigit() or c == "+")


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _find_farmer_by_phone(conn, phone):
    row = conn.execute(
        "SELECT phone, name, village, language FROM farmers WHERE phone = ?",
        (phone,),
    ).fetchone()
    return dict(row) if row else None


def _find_farmer_by_chat(conn, chat_id):
    row = conn.execute(
        "SELECT phone, name, village, language FROM farmers "
        "WHERE telegram_chat_id = ?",
        (chat_id,),
    ).fetchone()
    return dict(row) if row else None


def _link_chat(conn, phone, chat_id):
    conn.execute(
        "UPDATE farmers SET telegram_chat_id = ?, updated_at = ? "
        "WHERE phone = ?",
        (chat_id, _now_iso(), phone),
    )
    conn.commit()


def _unlink_chat(conn, chat_id):
    n = conn.execute(
        "UPDATE farmers SET telegram_chat_id = NULL, updated_at = ? "
        "WHERE telegram_chat_id = ?",
        (_now_iso(), chat_id),
    ).rowcount
    conn.commit()
    return n


# ---------------------------------------------------------------------------
# Command handlers (slash)
# ---------------------------------------------------------------------------
def cmd_start(conn, chat_id):
    existing = _find_farmer_by_chat(conn, chat_id)
    if existing:
        return (
            f"Namaste {existing['name']} ji! You are already registered "
            f"(phone {existing['phone']}). Ask me anything about your "
            f"stock, mandi prices, or the weather. I remember our "
            f"conversation.\n\n"
            f"Commands:\n"
            f"  /whoami        -- your registration\n"
            f"  /unregister    -- stop receiving messages"
        )
    return (
        "Welcome to Agri-Agent! I send daily mandi advice for Pune "
        "district AND answer your questions in chat.\n\n"
        "First, register with your phone number:\n"
        "   /register 9876500001\n\n"
        "Then ask anything -- 'which mandi is best for onion?', "
        "'should I go today?', 'what is my stock?'."
    )


def cmd_register(conn, chat_id, args):
    phone = _normalise_phone(args)
    if not phone:
        return "Please include your phone number:\n   /register 9876500001"
    farmer = _find_farmer_by_phone(conn, phone)
    if farmer is None:
        return (f"Sorry, phone {phone} is not registered as an Agri-Agent "
                f"farmer. Please contact the team to be added.")
    already = _find_farmer_by_chat(conn, chat_id)
    if already and already["phone"] != phone:
        return (f"This Telegram account is already linked to "
                f"{already['name']} ({already['phone']}). "
                f"Use /unregister first if you need to switch.")
    _link_chat(conn, phone, chat_id)
    return (f"Registered! {farmer['name']} ji, you will now receive "
            f"daily advice for {farmer['village'] or 'your village'}. "
            f"You can also ask me questions anytime.")


def cmd_whoami(conn, chat_id):
    f = _find_farmer_by_chat(conn, chat_id)
    if not f:
        return "Not registered yet. Send:  /register <your phone>"
    return (f"Registered as {f['name']} ({f['phone']}), "
            f"village {f['village'] or '-'}, language {f['language'] or 'en'}.")


def cmd_unregister(conn, chat_id):
    n = _unlink_chat(conn, chat_id)
    return ("Unregistered. You will no longer receive daily advice."
            if n else
            "No registration found for this Telegram account.")


# ---------------------------------------------------------------------------
# Free-form messages -> LangGraph agent
# ---------------------------------------------------------------------------
def cmd_chat(conn, chat_id, text):
    """Forward a non-command message to the conversational agent."""
    farmer = _find_farmer_by_chat(conn, chat_id)
    if not farmer:
        return ("Please /register your phone first so I know who is "
                "asking. Example:  /register 9876500001")

    _send_typing(chat_id)

    try:
        from agent_memory import ask_agent_with_memory
        result = ask_agent_with_memory(
            message=text,
            phone=farmer["phone"],
            language=(farmer.get("language") or "en").lower(),
        )
        answer = (result.get("summary") or "").strip()
        if not answer:
            answer = "(no answer produced)"
        return answer
    except Exception as e:
        return f"(agent error: {type(e).__name__}: {e})"


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
def handle_message(conn, msg):
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    if not chat_id or not text:
        return

    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        if "@" in cmd:
            cmd = cmd.split("@", 1)[0]

        if cmd == "/start":
            reply = cmd_start(conn, chat_id)
        elif cmd == "/register":
            reply = cmd_register(conn, chat_id, args)
        elif cmd == "/whoami":
            reply = cmd_whoami(conn, chat_id)
        elif cmd == "/unregister":
            reply = cmd_unregister(conn, chat_id)
        else:
            reply = "Unknown command. Try /start for help."
    else:
        # Anything not a slash-command -> conversational agent
        reply = cmd_chat(conn, chat_id, text)

    _send_message(chat_id, reply)
    print(f"  chat={chat_id}  <-  {text!r}  ->  reply sent")


def main():
    conn = init_db()
    print("Agri-Agent Telegram bot listening... (Ctrl+C to stop)")
    offset = None
    while True:
        for u in _get_updates(offset):
            offset = u["update_id"] + 1
            msg = u.get("message") or u.get("edited_message")
            if not msg:
                continue
            try:
                handle_message(conn, msg)
            except Exception as e:
                print(f"  handle_message error: {type(e).__name__}: {e}")
        time.sleep(0.5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
