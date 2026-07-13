"""Stage E.2 -- LLM message layer.

Reads the JSON that Stage E.1 (daily_advice.py) writes and turns each
farmer's list of nudges into ONE short, natural-language message in
that farmer's preferred language (English / Hindi / Marathi).

Pipeline
--------
    daily_advice_YYYY-MM-DD.json  (from E.1)
              |
              v
     [group nudges by farmer]
              |
              v
    [LLM: nudges -> one short message in farmer.language]
              |
              v
   daily_messages_YYYY-MM-DD.json  (input to E.3: Telegram/WhatsApp)

Why one message per farmer
--------------------------
If Manish has WEATHER_BLOCK + two DEADLINE_WARNINGs + a SELL_SIGNAL, we
send ONE combined message ("It's raining today, but you were planning to
sell tomato tomorrow and today's tomato price is at its peak -- go
tomorrow morning if rain lets up"), NOT four separate messages. Farmers
resent notification spam.

Why the LLM
-----------
Templating 4 English variants is easy. Templating 4 x 3 = 12 language
variants that read naturally is not -- pluralisation, honorifics, unit
words (quintal vs kg vs bag), and idiom differ. A tiny Haiku/mini call
is cheaper than maintaining 12 template files by hand.

Guardrails
----------
The prompt is strict: use only the numbers we give you, don't invent
mandi names, keep it under 4 short sentences, no emojis unless flagged.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from db import init_db


MODEL_NAME = os.environ.get("AGRI_WRITER_MODEL", "gpt-4o-mini")

LANG_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "mr": "Marathi",
}


SYSTEM_PROMPT = """You are the message writer for Agri-Agent, an SMS/chat \
advisor for small farmers in Pune district, India.

You receive a farmer's profile and a JSON list of NUDGES (one per issue). \
Your job: produce ONE short, natural message that combines all nudges \
into a single friendly note the farmer can read on their phone.

STRICT RULES:
1. Write in the farmer's language: {lang_name}. No mixing.
2. Use the farmer's NAME once at the start, respectfully (Ji / -ji for \
   Hindi and Marathi is fine).
3. Use ONLY the numbers, dates, mandi names, and crop names given in \
   the nudges. NEVER invent a price, a mandi, or a distance.
4. Combine related items instead of listing them: if WEATHER_BLOCK and \
   DEADLINE_WARNING both apply, mention the deadline AND the weather in \
   one sentence.
5. Keep it under 4 short sentences. Aim for < 400 characters.
6. Order by urgency: HIGH first, then MEDIUM, then LOW.
7. No emojis. No hashtags. No links. No English words in Hindi/Marathi \
   messages except for numbers, currency (Rs), units (quintal / q), \
   and proper nouns like "Onion" -- prefer the local word (kanda / \
   kande / pyaaz) if you know it.
8. End with a very short warm sign-off (e.g. "Take care." / "Kaljipoorvak.").

Return ONLY the message text. No headings, no JSON, no explanation."""


def _load_advice(path: str) -> dict:
    with open(path) as fh:
        return json.load(fh)


def _farmers_by_phone(conn) -> dict[str, dict]:
    """phone -> profile dict (includes language)."""
    rows = conn.execute(
        "SELECT phone, name, village, language FROM farmers"
    ).fetchall()
    return {r["phone"]: dict(r) for r in rows}


def _group_nudges(nudges: list[dict]) -> dict[str, list[dict]]:
    """phone -> list of that farmer's nudges."""
    out: dict[str, list[dict]] = {}
    for n in nudges:
        out.setdefault(n["farmer_phone"], []).append(n)
    return out


def _urgency_key(n: dict) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(n.get("urgency"), 3)


def _write_one(llm: ChatOpenAI, farmer: dict,
               nudges: list[dict]) -> str:
    """One LLM call -> one message string."""
    lang_code = (farmer.get("language") or "en").lower()
    lang_name = LANG_NAMES.get(lang_code, "English")

    nudges_sorted = sorted(nudges, key=_urgency_key)
    payload = {
        "farmer": {
            "name":     farmer["name"],
            "village":  farmer.get("village") or "",
            "language": lang_code,
        },
        "nudges": nudges_sorted,
    }

    sys_msg = SystemMessage(content=SYSTEM_PROMPT.format(lang_name=lang_name))
    hum_msg = HumanMessage(content=(
        f"Write the message now. Input:\n\n"
        f"{json.dumps(payload, indent=2, ensure_ascii=False)}"
    ))
    resp = llm.invoke([sys_msg, hum_msg])
    return (resp.content or "").strip()


def write_daily_messages(advice_path: Optional[str] = None,
                          out_path: Optional[str] = None,
                          today: Optional[date] = None) -> list[dict]:
    """End-to-end: read advice JSON, produce messages JSON.

    Returns the list of messages as dicts.
    """
    today = today or date.today()
    advice_path = advice_path or f"daily_advice_{today.isoformat()}.json"
    out_path    = out_path    or f"daily_messages_{today.isoformat()}.json"

    advice = _load_advice(advice_path)
    nudges = advice.get("nudges", [])
    if not nudges:
        print(f"No nudges in {advice_path}; nothing to write.")
        with open(out_path, "w") as fh:
            json.dump({"date": today.isoformat(), "messages": []}, fh, indent=2)
        return []

    conn = init_db()
    farmers = _farmers_by_phone(conn)
    grouped = _group_nudges(nudges)

    llm = ChatOpenAI(model=MODEL_NAME, temperature=0.2)

    messages: list[dict] = []
    for phone, farmer_nudges in grouped.items():
        farmer = farmers.get(phone) or {
            "phone": phone, "name": farmer_nudges[0]["farmer_name"],
            "village": farmer_nudges[0].get("farmer_village") or "",
            "language": "en",
        }
        try:
            text = _write_one(llm, farmer, farmer_nudges)
        except Exception as e:
            text = f"(LLM error: {type(e).__name__}: {e})"

        messages.append({
            "phone":    phone,
            "name":     farmer["name"],
            "village":  farmer.get("village") or "",
            "language": (farmer.get("language") or "en").lower(),
            "nudge_count": len(farmer_nudges),
            "triggers": sorted({n["trigger"] for n in farmer_nudges}),
            "message":  text,
        })

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"date": today.isoformat(), "messages": messages},
                  fh, indent=2, ensure_ascii=False)

    _print_messages(today, messages, out_path)
    return messages


def _print_messages(today, messages, out_path) -> None:
    print()
    print(f"===  Daily messages for {today.isoformat()}  ===")
    print(f"     messages written: {len(messages)}  ->  {out_path}")
    print()
    for m in messages:
        print(f"  -- {m['name']} ({m['phone']}, {m['language']}) "
              f"[{m['nudge_count']} nudge(s): {', '.join(m['triggers'])}]")
        for line in (m["message"] or "").splitlines():
            print(f"      {line}")
        print()


if __name__ == "__main__":
    # Optional: pass a specific date on the command line.
    d = None
    if len(sys.argv) > 1:
        try:
            d = date.fromisoformat(sys.argv[1])
        except ValueError:
            print(f"usage: python advice_writer.py [YYYY-MM-DD]")
            sys.exit(1)
    write_daily_messages(today=d)
