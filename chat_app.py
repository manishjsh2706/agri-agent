"""Browser chatbot for the Agri Agent  (FastAPI version).

Run with:

    pip install fastapi uvicorn
    python chat_app.py

Then open http://localhost:5000 in your browser.
"""

import re
import sys

try:
    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel
except ImportError:
    sys.exit("Missing dependency. Run:  pip install fastapi uvicorn")

from db import init_db
from comparison import compare_mandis
from pune_mandis import PUNE_MANDIS
from farmer_profile import get_farmer, list_stock
from history_query import get_crop_history
from best_window import best_window


DEFAULT_FARMER = {
    "name":    "Test farmer",
    "lat":     18.4956,
    "lon":     73.8588,
    "vehicle": "mini_truck",
}
DEFAULT_QUANTITY = 10
DEFAULT_RADIUS_KM = 60
STATE    = "Maharashtra"
DISTRICT = "Pune"


KNOWN_CROPS = [
    "Onion", "Tomato", "Wheat", "Soyabean", "Soybean", "Tur", "Arhar",
    "Potato", "Cotton", "Maize", "Bajra", "Jowar",
    "Mango", "Banana", "Grapes",
]

KNOWN_LOCATIONS = {
    "pune":         (18.4956, 73.8588),
    "hadapsar":     (18.5089, 73.9259),
    "chinchwad":    (18.6420, 73.7860),
    "baner":        (18.5599, 73.7806),
    "kothrud":      (18.5074, 73.8077),
    "wagholi":      (18.5800, 73.9692),
    "pimpri":       (18.6298, 73.7997),
    "moshi":        (18.6650, 73.8410),
    "katraj":       (18.4570, 73.8650),
    "shivajinagar": (18.5300, 73.8470),
    "khed":         (18.8451, 73.9008),
    "chakan":       (18.7600, 73.8429),
    "baramati":     (18.1514, 74.5800),
    "indapur":      (18.1167, 75.0167),
    "junnar":       (19.2050, 73.8779),
}

FORECAST_TRIGGERS = [
    "sell now", "sell today", "should i sell", "when should i sell",
    "when to sell", "wait", "forecast", "predict", "prediction",
    "next week", "tomorrow", "future price", "best time",
]

VEHICLE_WORDS = {
    "tractor":        "tractor_trolley",
    "trolley":        "tractor_trolley",
    "tractor_trolley":"tractor_trolley",
    "minitruck":      "mini_truck",
    "mini":           "mini_truck",
    "minitempo":      "mini_truck",
    "tempo":          "mini_truck",
    "mini_truck":     "mini_truck",
    "truck":          "truck",
    "lorry":          "truck",
}


def parse_message(msg: str) -> dict:
    text = msg.lower()
    out = {
        "crop":        None,
        "location":    None,
        "loc_name":    None,
        "vehicle":     None,
        "quantity":    None,
        "is_forecast": False,
    }

    for c in KNOWN_CROPS:
        if re.search(rf"\b{re.escape(c.lower())}\b", text):
            out["crop"] = c
            break

    for name, latlon in KNOWN_LOCATIONS.items():
        if re.search(rf"\b{name}\b", text):
            out["location"] = latlon
            out["loc_name"] = name.title()
            break

    for word, v in sorted(VEHICLE_WORDS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(word)}\b", text):
            out["vehicle"] = v
            break

    m = re.search(r"\b(\d{1,4})\b", text)
    if m:
        out["quantity"] = int(m.group(1))

    out["is_forecast"] = any(trig in text for trig in FORECAST_TRIGGERS)
    return out


def fetch_latest_for_crop(conn, state, district, crop):
    rows = conn.execute(
        """
        SELECT market, commodity, variety, grade,
               min_price, modal_price, max_price, arrival_date
          FROM prices
         WHERE state = ?
           AND district = ?
           AND LOWER(commodity) = LOWER(?)
        """,
        (state, district, crop),
    ).fetchall()
    return [dict(r) for r in rows]


def _forecast_answer(conn, crop: str, model: str = "holt_winters") -> dict:
    """Route: farmer wants to know whether to sell now or wait."""
    history = get_crop_history(conn, STATE, DISTRICT, crop)
    if not history:
        return {
            "summary": (f"I don't have any price history for {crop} in Pune yet. "
                        f"Run the daily fetch a few times and try again."),
            "ranking": [], "notes": [],
        }
    if len(history) < 21:
        return {
            "summary": (f"Only {len(history)} days of {crop} history so far. "
                        f"Forecasting needs at least 21 days; showing the "
                        f"latest price for now."),
            "ranking": [], "notes":
                [f"Latest median price for {crop}: Rs {history[-1][1]:.0f}/q "
                 f"on {history[-1][0]}."],
        }

    r = best_window(history, days_ahead=7, model=model)
    action_words = {
        "sell_today":   "SELL TODAY",
        "wait":         f"WAIT ~{r['best_day_index']} day(s)",
        "indifferent":  "SELL WHENEVER convenient",
    }
    summary = (
        f"For {crop}: today's typical Pune price is Rs "
        f"{r['todays_price']:.0f}/q. "
        f"Recommendation: {action_words[r['action']]}. "
        f"Best expected price Rs {r['expected_price']:.0f}/q on "
        f"{r['best_day_date']} ({r['gain_vs_today_pct']:+.2f}%). "
        f"Confidence: {r['confidence']}."
    )
    notes = [
        f"Model: {r['model']} (best on our validation leaderboard).",
        "7-day forecast: " + ", ".join(f"Rs {x:.0f}" for x in r["forecast"]),
        f"Based on {len(history)} days of median-per-day price history.",
    ]
    return {"summary": summary, "ranking": [], "notes": notes}


def answer(message: str, phone: str = "") -> dict:
    parsed = parse_message(message)
    crop = parsed["crop"]

    if not crop:
        return {
            "summary": ("Sorry, I didn't catch a crop. Try a message like "
                        "'onion' or 'wheat from hadapsar with truck', or "
                        "ask 'should I sell my onion today or wait?'"),
            "ranking": [],
            "notes":   [f"I know these crops: {', '.join(KNOWN_CROPS)}."],
        }

    conn = init_db()

    if parsed.get("is_forecast"):
        return _forecast_answer(conn, crop)

    farmer = dict(DEFAULT_FARMER)
    registered = get_farmer(conn, phone) if phone else None
    if registered:
        farmer["lat"]     = registered["latitude"]
        farmer["lon"]     = registered["longitude"]
        farmer["vehicle"] = registered["vehicle"]
        farmer["name"]    = registered["name"]
        where_default = registered.get("village") or registered["name"]
    else:
        where_default = "default location"

    if parsed["location"]:
        farmer["lat"], farmer["lon"] = parsed["location"]
    if parsed["vehicle"]:
        farmer["vehicle"] = parsed["vehicle"]

    quantity = parsed["quantity"]
    if quantity is None and registered:
        from_stock = [s for s in list_stock(conn, phone)
                      if s["crop"].lower() == crop.lower()]
        if from_stock:
            quantity = sum(s["quantity_q"] for s in from_stock)
    if quantity is None:
        quantity = DEFAULT_QUANTITY

    where = parsed["loc_name"] or where_default

    rows = fetch_latest_for_crop(conn, STATE, DISTRICT, crop)
    if not rows:
        return {
            "summary": (f"No recent prices for {crop} in Pune in the database. "
                        f"Run `python fetch_mandi_prices.py` to refresh."),
            "ranking": [], "notes": [],
        }

    result = compare_mandis(
        prices=rows,
        mandi_locations=PUNE_MANDIS,
        farmer_lat=farmer["lat"],
        farmer_lon=farmer["lon"],
        vehicle=farmer["vehicle"],
        crop=crop,
        radius_km=DEFAULT_RADIUS_KM,
        quantity_quintals=quantity,
    )

    if not result["ranking"]:
        return {
            "summary": (f"Found prices for {crop}, but no usable mandi within "
                        f"{DEFAULT_RADIUS_KM} km of {where}."),
            "ranking": [],
            "notes":   ([f"Excluded for radius: {result['excluded_for_radius']}"]
                        if result["excluded_for_radius"] else []),
        }

    top = result["ranking"][0]
    summary = (
        f"For {crop} from {where}, vehicle {farmer['vehicle']}, "
        f"{quantity} quintals -- BEST: go to {top['market']} for about "
        f"Rs {top['net_price_per_quintal']:.0f}/quintal after transport."
    )
    notes = []
    if result["low_confidence"]:
        notes.append("All nearby data is more than 2 days old; treat as low confidence.")
    elif result["freshness_warning_for"]:
        notes.append("Data for " + ", ".join(result["freshness_warning_for"])
                     + " is older than 2 days.")
    if result["excluded_for_radius"]:
        notes.append("Excluded for distance: " + ", ".join(result["excluded_for_radius"]))
    return {"summary": summary, "ranking": result["ranking"], "notes": notes}


INTENT_PHRASES = [
    # Future intent (record for later)
    "planning to sell", "plan to sell", "want to sell", "will sell",
    "going to sell", "intend to sell", "hoping to sell",
    "next week", "next month", "next friday", "next monday",
    "by friday", "by monday", "by next", "in a few days",
    "later", "not right now", "remind me", "remember", "record",

    # Travel planning today/tomorrow (needs weather check + comparison)
    "should i go", "should i visit", "should i travel",
    "go today", "go tomorrow", "visit today", "visit tomorrow",
    "travel today", "travel tomorrow",
    "trip today", "trip tomorrow",
    "is it safe", "rain today", "rain tomorrow",
    "weather today", "weather tomorrow",
]


def answer_smart(message: str, phone: str = "") -> dict:
    """Production routing: try the fast keyword parser first; only call
    the LLM agent when the parser cannot identify a crop OR when the
    message expresses a FUTURE intent (planning to sell, next week, etc)."""
    parsed = parse_message(message)
    text_low = message.lower()

    is_future_intent = any(p in text_low for p in INTENT_PHRASES)

    # Fast path: rules found a crop AND it's an immediate "help me now"
    # question -> use rules (mandi comparison). Skip if it's a future intent.
    if parsed["crop"] and not is_future_intent:
        result = answer(message, phone=phone)
        result.setdefault("notes", []).append("Handled by rules (no AI needed).")
        return result

    # Slow path: rules gave up -> defer to the LLM agent (WITH memory).
    try:
        from agent_memory import ask_agent_with_memory
        r = ask_agent_with_memory(message, phone=phone)
        trace = r.get("tool_trace", [])
        tool_names = ", ".join(t["tool"] for t in trace) if trace else "(no tools)"
        return {
            "summary": r["summary"],
            "ranking": [],
            "notes":   [f"AI called tools: {tool_names}"],
        }
    except Exception as e:
        return {
            "summary": ("I couldn't understand a crop from that, and my AI "
                        "helper is unavailable. Try mentioning the crop by "
                        "name, e.g. 'onion'."),
            "ranking": [],
            "notes":   [f"AI unavailable: {type(e).__name__}"],
        }


class AskRequest(BaseModel):
    message: str = ""
    phone:   str = ""


app = FastAPI(
    title="Agri Agent",
    description="Pune mandi advisor -- live recommendations from mandi_prices.db.",
)


@app.get("/", response_class=HTMLResponse)
def home():
    return INDEX_HTML


@app.post("/ask")
def ask(req: AskRequest):
    """Smart auto-routing endpoint. Uses rules if it can, falls back to LLM."""
    msg   = (req.message or "").strip()
    phone = (req.phone   or "").strip()
    if not msg:
        return {"summary": "Please type something.", "ranking": [], "notes": []}
    return answer_smart(msg, phone=phone)


@app.post("/ask_ai")
def ask_ai(req: AskRequest):
    """LLM-routed answer. Requires OPENAI_API_KEY in .env."""
    msg   = (req.message or "").strip()
    phone = (req.phone   or "").strip()
    if not msg:
        return {"summary": "Please type something.", "ranking": [], "notes": []}
    try:
        from agent import ask_agent
        result = ask_agent(msg, phone=phone)
        trace_note = "AI called tools: " + ", ".join(
            t["tool"] for t in result.get("tool_trace", [])
        ) if result.get("tool_trace") else "AI answered without tools."
        return {
            "summary": result["summary"],
            "ranking": [],
            "notes":   [trace_note],
        }
    except Exception as e:
        return {
            "summary": f"AI agent unavailable: {type(e).__name__}: {e}",
            "ranking": [],
            "notes":   ["Check that OPENAI_API_KEY is set in .env and langchain packages are installed."],
        }


@app.get("/me")
def whoami(phone: str = ""):
    if not phone.strip():
        return {"registered": False, "message": "Please pass a phone."}
    conn = init_db()
    f = get_farmer(conn, phone)
    if not f:
        return {"registered": False, "message": "Not registered."}
    return {"registered": True, "farmer": f, "stock": list_stock(conn, phone)}


INDEX_HTML = """<!doctype html>
<html lang=en>
<head>
<meta charset=utf-8>
<title>Agri Agent - Pune Mandi Advisor</title>
<style>
  body { margin: 0; font-family: -apple-system, Segoe UI, Roboto, sans-serif;
         background: #f5f5f0; color: #222; }
  header { padding: 14px 20px; background: #1f3864; color: #fff; }
  header h1 { margin: 0; font-size: 18px; font-weight: 500; }
  header .sub { font-size: 12px; opacity: .85; margin-top: 4px; }
  #wrap { max-width: 760px; margin: 0 auto; padding: 16px; }
  #chat { background: #fff; border: 1px solid #ddd; border-radius: 10px;
          padding: 16px; min-height: 60vh; max-height: 70vh; overflow-y: auto; }
  .msg { margin: 8px 0; padding: 10px 14px; border-radius: 10px;
         max-width: 92%; line-height: 1.45; white-space: pre-wrap; }
  .msg.user { background: #185fa5; color: #fff;
              margin-left: auto; border-bottom-right-radius: 2px; }
  .msg.bot  { background: #f1efe8; color: #222; border-bottom-left-radius: 2px; }
  .msg table { border-collapse: collapse; margin-top: 8px; font-size: 13px; }
  .msg th, .msg td { padding: 4px 8px; border-bottom: 1px solid #ddd;
                     text-align: left; white-space: nowrap; }
  .msg th { background: #d5e8f0; }
  .msg .note { margin-top: 8px; color: #5f5e5a; font-size: 13px; font-style: italic; }
  form { display: flex; gap: 8px; margin-top: 12px; }
  input[type=text] { flex: 1; padding: 10px 14px; font-size: 15px;
                     border: 1px solid #bbb; border-radius: 8px; outline: none; }
  input[type=text]:focus { border-color: #185fa5; }
  button { padding: 10px 18px; background: #185fa5; color: #fff;
           border: none; border-radius: 8px; font-size: 15px; cursor: pointer; }
  button:hover { background: #0c447c; }
  .examples { font-size: 13px; color: #5f5e5a; margin-top: 6px; }
  .examples code { background: #eee; padding: 1px 5px; border-radius: 3px; }
  .idbar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px;
           background: #fff; border: 1px solid #ddd; border-radius: 8px;
           padding: 8px 12px; font-size: 14px; }
  .idbar input { flex: 0 1 220px; padding: 6px 10px; border: 1px solid #bbb;
                 border-radius: 6px; outline: none; font-size: 14px; }
  .idbar input:focus { border-color: #185fa5; }
  .idbar button { padding: 6px 12px; font-size: 14px; background: #185fa5;
                  color: #fff; border: none; border-radius: 6px; cursor: pointer; }
  .idbar .status { color: #5f5e5a; margin-left: 4px; }
  .idbar .status.ok { color: #185fa5; font-weight: 500; }
</style>
</head>
<body>
<header>
  <h1>Agri Agent &mdash; Pune Mandi Advisor</h1>
  <div class=sub>Live recommendations from mandi_prices.db &middot; Pune district</div>
</header>
<div id=wrap>
  <div class=idbar>
    <label for=phone>Your phone:</label>
    <input type=text id=phone placeholder="e.g. 9876543210" inputmode="tel">
    <button id=meBtn type=button>Identify</button>
    <span class=status id=who>Guest</span>
  </div>
  <div id=chat></div>
  <form id=f>
    <input type=text id=m placeholder="Try: onion  |  should I sell onion or wait  |  wheat from hadapsar with truck" autofocus>
    <button>Send</button>
  </form>
  <div class=examples>
    Examples:
    <code>onion</code>
    <code>should i sell onion today or wait</code>
    <code>predict wheat next week</code>
    <code>tomato from baramati</code>
  </div>
</div>

<script>
const chat  = document.getElementById('chat');
const form  = document.getElementById('f');
const inp   = document.getElementById('m');
const phone = document.getElementById('phone');
const who   = document.getElementById('who');
const meBtn = document.getElementById('meBtn');

function addUser(text){
  const d = document.createElement('div');
  d.className = 'msg user';
  d.textContent = text;
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
}
function addBot(reply){
  const d = document.createElement('div');
  d.className = 'msg bot';
  if (reply.summary){
    const s = document.createElement('div');
    s.textContent = reply.summary;
    d.appendChild(s);
  }
  if (reply.ranking && reply.ranking.length){
    const t = document.createElement('table');
    const head = t.insertRow();
    ['#','Mandi','Distance','Modal','Transport/q','Net/q','As of'].forEach(h=>{
      const th = document.createElement('th'); th.textContent = h; head.appendChild(th);
    });
    reply.ranking.forEach((r,i)=>{
      const row = t.insertRow();
      const cells = [
        String(i+1),
        r.market + (r.is_stale ? ' *' : ''),
        r.distance_km.toFixed(1) + ' km',
        'Rs ' + Math.round(r.gross_modal_price),
        'Rs ' + Math.round(r.transport_cost_per_quintal),
        'Rs ' + Math.round(r.net_price_per_quintal),
        r.arrival_date,
      ];
      cells.forEach(v => { const td = row.insertCell(); td.textContent = v; });
    });
    d.appendChild(t);
  }
  (reply.notes||[]).forEach(n=>{
    const p = document.createElement('div');
    p.className = 'note';
    p.textContent = n;
    d.appendChild(p);
  });
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
}

addBot({summary:"Hi! Ask me which mandi to visit, or ask 'should I sell my onion today or wait?'"});

form.onsubmit = async (e)=>{
  e.preventDefault();
  const text = inp.value.trim();
  if (!text) return;
  addUser(text);
  inp.value = '';
  const r = await fetch('/ask',{
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({message:text, phone:(phone.value||'').trim()})
  });
  const data = await r.json();
  addBot(data);
};

meBtn.onclick = async ()=>{
  const ph = (phone.value||'').trim();
  if (!ph){ who.textContent = 'Guest'; who.className='status'; return; }
  const r = await fetch('/me?phone=' + encodeURIComponent(ph));
  const data = await r.json();
  if (data.registered){
    who.textContent = data.farmer.name + (data.farmer.village ? ' ('+data.farmer.village+')' : '');
    who.className = 'status ok';
    const lines = ['Identified you as ' + data.farmer.name + '. '
                   + 'Vehicle: ' + data.farmer.vehicle + '. '
                   + 'Crops: ' + (data.farmer.crops || '(none)') + '.'];
    if (data.stock && data.stock.length){
      lines.push('Current stock to sell:');
      data.stock.forEach(s => lines.push('  - ' + s.crop + ': ' + s.quantity_q + ' quintals'));
    }
    addBot({summary: lines.join('\\n')});
  } else {
    who.textContent = 'Not registered';
    who.className = 'status';
    addBot({summary: 'Phone ' + ph + ' is not registered yet. The chat will use the default location/vehicle.'});
  }
};
</script>
</body>
</html>"""


if __name__ == "__main__":
    print("Starting Agri Agent chatbot at  http://localhost:5000")
    print("API docs available at         http://localhost:5000/docs")
    uvicorn.run("chat_app:app", host="127.0.0.1", port=5000, reload=False)
