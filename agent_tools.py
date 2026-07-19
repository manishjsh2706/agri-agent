"""LangChain tool wrappers around our existing engine.

Each @tool below is a small, typed function the LLM can call. The LLM
sees only the name, docstring, and argument schema -- it does not see
the real database or model code. That's the whole point of an agent:
the LLM decides WHICH tool to call and with WHAT arguments; our code
executes them safely.

Public
------
    ALL_TOOLS  -- list of every tool, ready to be bound to an LLM.
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
from typing import Optional

from langchain_core.tools import tool

from db import init_db
from comparison import compare_mandis
from pune_mandis import PUNE_MANDIS, find_mandi_by_name
from history_query import get_crop_history
from best_window import best_window
from farmer_profile import get_farmer, list_stock
from open_intents import create_intent, list_open_intents
from weather import get_daily_forecast
from scheme_tool import lookup_scheme_info_tool


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (sin(dlat / 2) ** 2
         + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2)
    return 2 * R * asin(sqrt(a))


# ---------------------------------------------------------------------------
# Tool: farmer profile lookup
# ---------------------------------------------------------------------------
@tool
def get_farmer_profile_tool(phone: str) -> dict:
    """Look up a registered farmer's profile and current stock by phone
    number. Returns village, coordinates, vehicle, crops list, and every
    'available' stock entry (crop + quantity in quintals).
    Use this FIRST when the user provides a phone number."""
    conn = init_db()
    f = get_farmer(conn, phone)
    if not f:
        return {"registered": False, "phone": phone}
    stock = [
        {"crop": s["crop"], "quantity_q": s["quantity_q"]}
        for s in list_stock(conn, phone)
    ]
    return {
        "registered": True,
        "name":       f["name"],
        "village":    f.get("village") or "",
        "latitude":   f["latitude"],
        "longitude":  f["longitude"],
        "vehicle":    f["vehicle"],
        "crops":      f.get("crops") or "",
        "stock":      stock,
    }


# ---------------------------------------------------------------------------
# Tool: current prices lookup (no math)
# ---------------------------------------------------------------------------
@tool
def get_current_prices_tool(crop: str) -> dict:
    """Return the latest prices for a crop across all Pune district
    mandis, one row per market with min / modal / max and the arrival
    date. Use this when the farmer asks 'what's the price of onion'
    without a location. Does NOT compute transport cost or ranking."""
    conn = init_db()
    rows = conn.execute(
        """
        SELECT market, variety, min_price, modal_price, max_price, arrival_date
          FROM prices
         WHERE state='Maharashtra' AND district='Pune'
           AND LOWER(commodity)=LOWER(?)
        """,
        (crop,),
    ).fetchall()
    if not rows:
        return {"crop": crop, "found": 0, "message": "No recent prices."}
    latest = {}
    for r in rows:
        m = r["market"]
        if m not in latest or r["arrival_date"] > latest[m]["arrival_date"]:
            latest[m] = dict(r)
    return {"crop": crop, "found": len(latest), "markets": list(latest.values())}


# ---------------------------------------------------------------------------
# Tool: mandi comparison (the money-maker)
# ---------------------------------------------------------------------------
@tool
def compare_mandis_tool(
    crop: str,
    farmer_lat: float,
    farmer_lon: float,
    vehicle: str = "mini_truck",
    quantity_quintals: float = 10,
    radius_km: float = 60,
) -> dict:
    """Rank nearby Pune mandis by NET price (modal price minus transport
    cost per quintal), given the farmer's location, vehicle and quantity.
    vehicle must be one of: tractor_trolley, mini_truck, truck.
    Use this when the farmer asks WHICH mandi to sell at.
    Do NOT use this to answer 'how far is X mandi?' -- use
    find_mandi_by_name_tool for name lookups."""
    conn = init_db()
    rows = conn.execute(
        """
        SELECT market, commodity, variety, min_price, modal_price,
               max_price, arrival_date
          FROM prices
         WHERE state='Maharashtra' AND district='Pune'
           AND LOWER(commodity)=LOWER(?)
        """,
        (crop,),
    ).fetchall()
    prices = [dict(r) for r in rows]
    if not prices:
        return {"error": f"no prices in DB for {crop}"}
    result = compare_mandis(
        prices=prices,
        mandi_locations=PUNE_MANDIS,
        farmer_lat=farmer_lat,
        farmer_lon=farmer_lon,
        vehicle=vehicle,
        crop=crop,
        radius_km=radius_km,
        quantity_quintals=quantity_quintals,
    )
    result["ranking"] = result.get("ranking", [])[:5]
    return result


# ---------------------------------------------------------------------------
# Tool: sell-now-vs-wait forecast
# ---------------------------------------------------------------------------
@tool
def best_window_tool(crop: str, model: str = "holt_winters") -> dict:
    """Forecast the next 7 days of prices for a crop and recommend
    whether to sell today or wait. Uses walk-forward-validated Holt-
    Winters by default. Requires at least ~21 days of price history in
    the database. Use this when the farmer asks WHEN to sell."""
    conn = init_db()
    history = get_crop_history(conn, "Maharashtra", "Pune", crop)
    if not history:
        return {"error": f"no history for {crop}"}
    if len(history) < 21:
        return {
            "warning": (f"only {len(history)} days of history; "
                        f"need at least 21 for a reliable forecast"),
            "latest_price": history[-1][1],
        }
    return best_window(history, days_ahead=7, model=model)


# ---------------------------------------------------------------------------
# Tool: list all registered farmers
# ---------------------------------------------------------------------------
@tool
def list_farmers_tool() -> dict:
    """List every registered farmer (phone + name + village). Use this
    ONLY if the user explicitly asks 'who is registered' -- otherwise
    prefer get_farmer_profile_tool with a specific phone."""
    conn = init_db()
    rows = conn.execute(
        "SELECT phone, name, village FROM farmers ORDER BY name"
    ).fetchall()
    return {"count": len(rows), "farmers": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Stage D.5 tools: open sell intents
# ---------------------------------------------------------------------------
@tool
def record_sell_intent_tool(
    phone: str,
    crop: str,
    quantity_q: Optional[float] = None,
    deadline: Optional[str] = None,
    notes: str = "",
) -> dict:
    """Record that a farmer PLANS to sell a crop. Call this whenever the
    farmer expresses intent like 'I want to sell my onions next week'.
    deadline is optional and must be an ISO date YYYY-MM-DD.
    Returns the new intent id."""
    conn = init_db()
    intent_id = create_intent(conn, phone=phone, crop=crop,
                              quantity_q=quantity_q, deadline=deadline,
                              notes=notes)
    return {"intent_id": intent_id, "status": "open",
            "phone": phone, "crop": crop, "quantity_q": quantity_q}


@tool
def list_my_intents_tool(phone: str) -> dict:
    """Show every open sell intent for a farmer. Call when the farmer
    asks 'what am I trying to sell' or 'do you remember what I said last time'."""
    conn = init_db()
    intents = list_open_intents(conn, phone=phone)
    return {"count": len(intents), "intents": intents}


# ---------------------------------------------------------------------------
# Stage D.2 tool: weather forecast
# ---------------------------------------------------------------------------
@tool
def get_weather_tool(
    latitude: float,
    longitude: float,
    days: int = 3,
) -> dict:
    """Fetch a daily weather forecast (temps, rain, WMO code) for a location.
    Use this BEFORE recommending a mandi trip, especially if the farmer plans
    to travel today or tomorrow. Returns 1-14 days of daily forecast,
    each with a 'safe_to_travel' hint like 'yes' / 'caution_rain' /
    'no_heavy_rain' / 'no_thunderstorm' / 'caution_heat'."""
    try:
        forecast = get_daily_forecast(latitude, longitude, days=days)
        return {"forecast": forecast}
    except Exception as e:
        return {"error": f"weather lookup failed: {type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# NEW: find a mandi by name (or nickname / suburb)
# ---------------------------------------------------------------------------
@tool
def find_mandi_by_name_tool(
    name: str,
    farmer_lat: Optional[float] = None,
    farmer_lon: Optional[float] = None,
    crop: Optional[str] = None,
) -> dict:
    """Look up a specific Pune-district mandi by name, nickname, or suburb.
    Use this whenever the farmer asks about a NAMED mandi -- e.g.
    'how far is Hadapsar mandi?' or 'what's the price at Chakan?'.
    Do NOT use compare_mandis_tool for name lookups; that tool ranks by
    net price, not by name.

    Accepts partial names ('manjri'), suburbs ('hadapsar' -> Pune(Manjri)),
    misspellings ('chaakan' -> Chakan), and trailing words ('Hadapsar mandi').

    Optionally pass farmer_lat/farmer_lon to include the straight-line
    distance in kilometres from the farmer. Optionally pass crop to include
    today's modal price at that mandi.

    Returns a dict with:
        found         (bool)
        matched_name  (canonical mandi name)
        latitude, longitude
        match_type    ('exact' / 'area_hint' / 'substring' / 'fuzzy')
        distance_km   (if farmer coords given)
        modal_price   (if crop given and price exists in DB)
        arrival_date  (if crop given)
    If nothing matches: {"found": False, "query": name}.
    """
    m = find_mandi_by_name(name)
    if m is None:
        return {"found": False, "query": name,
                "message": f"No Pune-district mandi matched '{name}'."}

    out = {
        "found":        True,
        "query":        m["query"],
        "matched_name": m["matched_name"],
        "latitude":     m["latitude"],
        "longitude":    m["longitude"],
        "match_type":   m["match_type"],
    }

    if farmer_lat is not None and farmer_lon is not None:
        out["distance_km"] = round(
            _haversine_km(float(farmer_lat), float(farmer_lon),
                          m["latitude"], m["longitude"]),
            1,
        )
    else:
        # No farmer coords -> we CANNOT compute distance. Tell the LLM
        # explicitly so it doesn't invent a number. This is the anti-
        # hallucination guard.
        out["distance_km"] = None
        out["distance_note"] = (
            "farmer_lat/farmer_lon were NOT provided, so distance was "
            "NOT computed. DO NOT guess or invent a distance. To answer "
            "'how far is X mandi?' correctly, first call "
            "get_farmer_profile_tool with the farmer's phone to obtain "
            "their latitude and longitude, then call this tool AGAIN "
            "passing those coordinates."
        )

    if crop:
        conn = init_db()
        row = conn.execute(
            """
            SELECT modal_price, min_price, max_price, arrival_date
              FROM prices
             WHERE state='Maharashtra' AND district='Pune'
               AND LOWER(commodity)=LOWER(?)
               AND (market=? OR market=?)
             ORDER BY arrival_date DESC
             LIMIT 1
            """,
            (crop, m["matched_name"], f"{m['matched_name']} APMC"),
          ).fetchone()
        if row:
            out["modal_price"]  = row["modal_price"]
            out["min_price"]    = row["min_price"]
            out["max_price"]    = row["max_price"]
            out["arrival_date"] = row["arrival_date"]
        else:
            out["price_note"] = (
                f"No recent {crop} price recorded at {m['matched_name']}."
            )

    return out


# ---------------------------------------------------------------------------
# NEW: list every crop traded recently at nearby mandis
# ---------------------------------------------------------------------------
@tool
def list_all_crops_near_me_tool(
    farmer_lat: float,
    farmer_lon: float,
    vehicle: str = "mini_truck",
    radius_km: float = 60,
    quantity_quintals: float = 10,
    phone: Optional[str] = None,
) -> dict:
    """List EVERY crop with recent Pune-district prices, one row per crop
    with its best-net-price mandi (given the farmer's location + vehicle).

    Use this when the farmer asks for "all rates", "sabhi rates", "har
    item ke bhaav", or any variant that means 'show me everything you
    have, not just my crops'.

    If `phone` is given, the tool also looks up the farmer's stock and
    returns the result PRE-SPLIT into two lists:
        your_stock   -- crops the farmer has in stock (highlight these)
        other_crops  -- everything else

    That way the LLM does not need to remember the stock separately --
    it can render the two lists directly.
    """
    conn = init_db()

    # Pick the most recent arrival_date first, then find the window of
    # rows within the last 3 days of that date -- lets us include crops
    # that were traded yesterday even if today has no report.
    row = conn.execute(
        "SELECT MAX(arrival_date) AS d FROM prices "
        "WHERE state='Maharashtra' AND district='Pune'"
    ).fetchone()
    newest = row["d"] if row and row["d"] else None
    if not newest:
        return {"count": 0, "crops": [], "message": "no Pune prices in DB"}

    # DISTINCT crops that have prices reported in this recent window.
    crops = [r["c"] for r in conn.execute(
        "SELECT DISTINCT commodity AS c FROM prices "
        "WHERE state='Maharashtra' AND district='Pune' "
        "ORDER BY commodity"
    ).fetchall()]

    if not crops:
        return {"count": 0, "crops": [], "message": "no crops in DB"}

    out_rows: list[dict] = []
    for crop in crops:
        # Reuse compare_mandis_tool's internals by calling the raw engine.
        rows = conn.execute(
            "SELECT market, commodity, variety, min_price, modal_price, "
            "       max_price, arrival_date "
            "FROM prices "
            "WHERE state='Maharashtra' AND district='Pune' "
            "  AND LOWER(commodity)=LOWER(?)",
            (crop,),
        ).fetchall()
        prices = [dict(r) for r in rows]
        if not prices:
            continue
        try:
            result = compare_mandis(
                prices=prices,
                mandi_locations=PUNE_MANDIS,
                farmer_lat=farmer_lat,
                farmer_lon=farmer_lon,
                vehicle=vehicle,
                crop=crop,
                radius_km=radius_km,
                quantity_quintals=quantity_quintals,
            )
        except Exception:
            continue
        ranking = result.get("ranking") or []
        if not ranking:
            continue
        top   = ranking[0]
        modal = top.get("gross_modal_price") or 0
        net   = top.get("net_price_per_quintal") or 0
        # Filter: don't emit crops whose top mandi has no meaningful price.
        # This kills the "Amla -- Rs0/q" style noise from crops that
        # appear in the schema but have zero/NULL modal_price today.
        if not modal or float(modal) <= 0:
            continue
        out_rows.append({
            "crop":         crop,
            "top_mandi":    top.get("market") or "",
            "net_price":    round(float(net),   2) if net else 0,
            "modal_price":  round(float(modal), 2),
            "distance_km":  round(float(top.get("distance_km") or 0), 1),
            "arrival_date": top.get("arrival_date"),
            "is_stale":     top.get("is_stale", False),
        })

    out_rows.sort(key=lambda r: r["crop"].lower())

    # --- Split by farmer's stock if a phone is provided --------------
    your_stock: list[dict] = []
    other_crops: list[dict] = out_rows
    stock_names: list[str] = []
    if phone:
        f = get_farmer(conn, phone)
        if f:
            stock_names = [s["crop"] for s in list_stock(conn, phone)]
            stock_set = {s.lower() for s in stock_names}
            your_stock  = [r for r in out_rows
                           if (r["crop"] or "").lower() in stock_set]
            other_crops = [r for r in out_rows
                           if (r["crop"] or "").lower() not in stock_set]

    return {
        "count":       len(out_rows),
        "as_of_date":  newest,
        "your_stock":  your_stock,
        "other_crops": other_crops,
        "stock_names": stock_names,
        "crops":       out_rows,   # kept for backward compat
    }


# ---------------------------------------------------------------------------
# Tool: list every crop traded at ONE specific mandi
# ---------------------------------------------------------------------------
@tool
def list_crops_at_mandi_tool(
    mandi_name: str,
    farmer_lat: Optional[float] = None,
    farmer_lon: Optional[float] = None,
    on_date: Optional[str] = None,
) -> dict:
    """List crops with prices at ONE specific mandi.

    Use this for a SINGLE named mandi's crop list, e.g.
    "aaj Pune(Manjri) me kya kya trade hue?",
    "what's being sold at Chakan today?",
    "Hadapsar mandi ke sab bhaav bata do".

    Optional `on_date` -- if given (as "DD/MM/YYYY" OR "DD-MM-YYYY"), the
    tool returns crops for EXACTLY that date instead of the last 7 days.
    Use this when the farmer asks about a specific date like
    "07-07-2026 ko kya trade hua tha?" or "kal Pune APMC me?".
    Without `on_date`, the tool returns the newest row per crop within
    the last 7 days.

    Fuzzy matches the mandi name via find_mandi_by_name (Hadapsar ->
    Pune(Manjri), etc.).

    Returns:
        {
          "matched_name": canonical mandi name,
          "match_type":   "exact" / "area_hint" / "substring" / "fuzzy",
          "distance_km":  farmer's distance to the mandi (if coords given),
          "count":        total crops found,
          "as_of_date":   most recent arrival_date across the crops,
          "crops": [
            {"crop": "Onion",  "modal_price": 2050.0,
             "arrival_date": "08/07/2026", "variety": "Local"},
            ...
          ]
        }
    If the mandi name doesn't match: {"found": False, "query": mandi_name}.
    """
    m = find_mandi_by_name(mandi_name)
    if m is None:
        return {"found": False, "query": mandi_name,
                "message": f"No Pune-district mandi matched '{mandi_name}'."}

    canonical = m["matched_name"]
    conn = init_db()

    from datetime import date, datetime
    STALENESS_DAYS = 7      # ignore crops last reported more than this ago
    PRICE_MIN      = 50     # sanity band -- filter unit-error rows
    PRICE_MAX      = 20000  # sanity band -- filter unit-error rows

    def _parse(s):
        s = (s or "").strip().replace("-", "/")
        try:
            return datetime.strptime(s, "%d/%m/%Y").date()
        except (ValueError, TypeError):
            return None

    today = date.today()
    target_date = _parse(on_date) if on_date else None
    if on_date and target_date is None:
        return {"error": (f"could not parse date '{on_date}'. "
                          f"Use DD/MM/YYYY or DD-MM-YYYY.")}

    # Pull every price row for this mandi (market may be "X" or "X APMC").
    rows = conn.execute(
        """
        SELECT commodity, variety, min_price, modal_price, max_price,
               arrival_date
          FROM prices
         WHERE state='Maharashtra' AND district='Pune'
           AND (market = ? OR market = ?)
           AND modal_price IS NOT NULL AND modal_price > 0
         ORDER BY commodity, arrival_date DESC
        """,
        (canonical, f"{canonical} APMC"),
    ).fetchall()

    # Group by commodity.
    #   * If target_date is set  -> keep only rows on that exact date.
    #   * Otherwise               -> keep newest row per crop (using
    #                                 parsed date objects, not strings).
    by_crop: dict[str, dict] = {}
    by_crop_date: dict[str, "date"] = {}
    for r in rows:
        row = dict(r)
        c = row["commodity"]
        d = _parse(row.get("arrival_date"))
        if d is None:
            continue
        if target_date is not None:
            if d != target_date:
                continue                 # skip rows for other dates
            by_crop[c] = row             # one row per crop on that date
            by_crop_date[c] = d
        else:
            prev_d = by_crop_date.get(c)
            if prev_d is None or d > prev_d:
                by_crop[c] = row
                by_crop_date[c] = d

    # Apply sanity + freshness filters and enrich.
    # Freshness is skipped when the caller asked for a specific date --
    # they explicitly WANT rows from that date, no matter how old.
    fresh_rows: list[dict] = []
    dropped_stale, dropped_sanity = 0, 0
    for row in by_crop.values():
        modal = float(row["modal_price"] or 0)
        if not (PRICE_MIN <= modal <= PRICE_MAX):
            dropped_sanity += 1
            continue
        arr = _parse(row.get("arrival_date"))
        days_old = (today - arr).days if arr else None
        if target_date is None:
            if days_old is None or days_old > STALENESS_DAYS:
                dropped_stale += 1
                continue
        fresh_rows.append({
            "crop":         row["commodity"],
            "variety":      row["variety"],
            "modal_price":  round(modal, 2),
            "min_price":    round(float(row["min_price"] or 0), 2),
            "max_price":    round(float(row["max_price"] or 0), 2),
            "arrival_date": row["arrival_date"],
            "days_old":     days_old,
            "is_stale":     days_old > 2,
        })

    # Sort: fresh first (by days_old asc), then alphabetical.
    fresh_rows.sort(key=lambda r: (r["days_old"], (r["crop"] or "").lower()))

    out_crops     = fresh_rows
    newest_overall = fresh_rows[0]["arrival_date"] if fresh_rows else None

    result = {
        "matched_name":      canonical,
        "match_type":        m["match_type"],
        "count":             len(out_crops),
        "as_of_date":        newest_overall,
        "crops":             out_crops,
        "dropped_stale":     dropped_stale,
        "dropped_sanity":    dropped_sanity,
        "staleness_days":    STALENESS_DAYS if target_date is None else None,
        "sanity_price_band": [PRICE_MIN, PRICE_MAX],
        "target_date":       target_date.strftime("%d/%m/%Y") if target_date else None,
    }

    if farmer_lat is not None and farmer_lon is not None:
        result["distance_km"] = round(
            _haversine_km(float(farmer_lat), float(farmer_lon),
                          m["latitude"], m["longitude"]),
            1,
        )

    if not out_crops:
        result["message"] = (
            f"{canonical} is a known mandi but has no recent prices in "
            f"the database."
        )

    return result



ALL_TOOLS = [
    get_farmer_profile_tool,
    get_current_prices_tool,
    compare_mandis_tool,
    best_window_tool,
    list_farmers_tool,
    record_sell_intent_tool,
    list_my_intents_tool,
    get_weather_tool,
    find_mandi_by_name_tool,
    list_all_crops_near_me_tool,
    list_crops_at_mandi_tool,
    lookup_scheme_info_tool,
]
