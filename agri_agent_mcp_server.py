"""Agri-Agent MCP server -- expose all 12 domain tools to any MCP client.

Wraps every LangChain @tool from agent_tools.py (and scheme_tool.py)
as an MCP tool. Any MCP-compatible client (Claude Desktop, Cursor,
Zed, Windsurf, MCP Inspector, etc.) can discover and invoke these.

Nothing about the underlying tools changes -- this file is purely a NEW
front door to the same domain logic. The Telegram bot continues to work
unchanged; this just adds an alternative way to reach the tools.

Stages:
    MCP.3 -- initial 3 tools (weather, mandi comparison, scheme lookup)
    MCP.4 -- ALL 12 tools wrapped (this file)
    MCP.5 -- test with MCP Inspector
    MCP.6 -- wire into Claude Desktop
    MCP.7 -- deploy to Oracle Cloud + git push

Run:
    python agri_agent_mcp_server.py

Waits silently on stdio for MCP client messages. That's normal.
"""

from __future__ import annotations

# ---- SQLite compatibility shim (must run first) -----------------------
# Chroma (via lookup_scheme_info_tool -> scheme_retriever) needs newer
# sqlite. Oracle Linux 9 ships sqlite 3.34; pysqlite3-binary is the fix.
try:
    __import__("pysqlite3")
    import sys as _sys
    _sys.modules["sqlite3"] = _sys.modules.pop("pysqlite3")
except ImportError:
    pass
# -----------------------------------------------------------------------

import json
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from mcp.server.fastmcp import FastMCP

# All 11 tools from agent_tools.py
from agent_tools import (
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
)
# 12th tool -- RAG scheme lookup
from scheme_tool import lookup_scheme_info_tool


# ---------------------------------------------------------------------------
# MCP server instance.
# The name "agri-agent" is what appears in the client's UI.
# ---------------------------------------------------------------------------
mcp = FastMCP("agri-agent")


# ---------------------------------------------------------------------------
# Helper: format underlying tool result for MCP.
# LangChain tools return dicts / lists; MCP expects string responses.
# We serialize to pretty-printed JSON (ensure_ascii=False keeps Hindi /
# Marathi characters readable; default=str catches things like dates).
# ---------------------------------------------------------------------------
def _fmt(result) -> str:
    """Serialize a tool's result as a JSON string for MCP."""
    if isinstance(result, str):
        return result
    return json.dumps(result, indent=2, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# TOOL 1 -- get_farmer_profile
# ---------------------------------------------------------------------------
@mcp.tool()
def get_farmer_profile(phone: str) -> str:
    """Look up a registered farmer's profile and current stock by phone number.

    Returns village, latitude/longitude, vehicle, crops list, and every
    'available' stock entry (crop + quantity in quintals).

    Call this FIRST when the user provides a phone number, before other
    farmer-specific queries.

    Args:
        phone: 10-digit farmer phone number (e.g., "9876500001").

    Returns:
        JSON string with farmer profile and stock, or 'not found' if the
        phone is not registered.
    """
    return _fmt(get_farmer_profile_tool.invoke({"phone": phone}))


# ---------------------------------------------------------------------------
# TOOL 2 -- get_current_prices
# ---------------------------------------------------------------------------
@mcp.tool()
def get_current_prices(crop: str) -> str:
    """Return the latest prices for a crop across all Pune district mandis.

    Returns one row per market with min / modal / max prices and the
    arrival date. Does NOT compute transport cost or ranking.

    Use when the farmer asks 'what's the price of onion?' without
    specifying a location.

    Args:
        crop: Crop name (e.g., "Onion", "Tomato", "Wheat", "Garlic").

    Returns:
        JSON string with per-mandi price data for the crop.
    """
    return _fmt(get_current_prices_tool.invoke({"crop": crop}))


# ---------------------------------------------------------------------------
# TOOL 3 -- compare_mandis
# ---------------------------------------------------------------------------
@mcp.tool()
def compare_mandis(
    crop: str,
    farmer_lat: float,
    farmer_lon: float,
    vehicle: str = "mini_truck",
    quantity_quintals: float = 10,
    radius_km: float = 60,
) -> str:
    """Rank nearby Pune-district mandis by NET price (modal price minus
    transport cost per quintal), given the farmer's location, vehicle,
    and quantity.

    Args:
        crop:              Crop name (e.g., "Onion", "Tomato").
        farmer_lat:        Farmer's latitude (decimal degrees).
        farmer_lon:        Farmer's longitude (decimal degrees).
        vehicle:           One of "tractor_trolley", "mini_truck", "truck".
                           Defaults to "mini_truck".
        quantity_quintals: How many quintals the farmer is selling.
                           Defaults to 10.
        radius_km:         Only consider mandis within this many km.
                           Defaults to 60.

    Returns:
        JSON string with the best mandi, ranked alternatives, and per-mandi
        gross price / travel cost / net price.
    """
    return _fmt(compare_mandis_tool.invoke({
        "crop":              crop,
        "farmer_lat":        farmer_lat,
        "farmer_lon":        farmer_lon,
        "vehicle":           vehicle,
        "quantity_quintals": quantity_quintals,
        "radius_km":         radius_km,
    }))


# ---------------------------------------------------------------------------
# TOOL 4 -- best_window (sell-now-vs-wait forecast)
# ---------------------------------------------------------------------------
@mcp.tool()
def best_window(crop: str, model: str = "holt_winters") -> str:
    """Forecast the next 7 days of prices for a crop and recommend whether
    to sell today or wait for a better day.

    Uses walk-forward-validated Holt-Winters by default. Requires at least
    ~21 days of historical price data in the database.

    Use when the farmer asks WHEN to sell (e.g., "should I sell today
    or wait?").

    Args:
        crop:  Crop name (e.g., "Onion", "Tomato", "Wheat").
        model: Forecast model. Defaults to "holt_winters".
               Alternatives: "ridge", "naive".

    Returns:
        JSON string with today's price, expected best-day price, expected
        best day date, action recommendation, and confidence.
    """
    return _fmt(best_window_tool.invoke({
        "crop":  crop,
        "model": model,
    }))


# ---------------------------------------------------------------------------
# TOOL 5 -- list_farmers
# ---------------------------------------------------------------------------
@mcp.tool()
def list_farmers() -> str:
    """List every registered farmer (phone + name + village).

    Use ONLY if the user explicitly asks "who is registered" or "which
    farmers are in the system". For a specific farmer, prefer
    get_farmer_profile instead.

    Returns:
        JSON string with a list of all farmer records.
    """
    return _fmt(list_farmers_tool.invoke({}))


# ---------------------------------------------------------------------------
# TOOL 6 -- record_sell_intent
# ---------------------------------------------------------------------------
@mcp.tool()
def record_sell_intent(
    phone: str,
    crop: str,
    quantity_q: Optional[float] = None,
    deadline: Optional[str] = None,
    notes: str = "",
) -> str:
    """Record a farmer's intent to sell a crop by a future date.

    Use when the farmer says something like "I want to sell my tomato
    by next Sunday" or "I'm planning to sell 30 quintals of onion".

    Args:
        phone:      Farmer's 10-digit phone number.
        crop:       Crop name (e.g., "Onion", "Tomato").
        quantity_q: Quantity in quintals. If omitted, uses the farmer's
                    current stock quantity for that crop.
        deadline:   Target date in YYYY-MM-DD format. If omitted, no
                    deadline is recorded.
        notes:      Free-text notes about the intent.

    Returns:
        JSON string confirming the intent was recorded, including the
        intent id.
    """
    args: dict = {"phone": phone, "crop": crop, "notes": notes}
    if quantity_q is not None:
        args["quantity_q"] = quantity_q
    if deadline is not None:
        args["deadline"] = deadline
    return _fmt(record_sell_intent_tool.invoke(args))


# ---------------------------------------------------------------------------
# TOOL 7 -- list_my_intents
# ---------------------------------------------------------------------------
@mcp.tool()
def list_my_intents(phone: str) -> str:
    """Show every open sell intent for a specific farmer.

    Use when the farmer asks "what am I trying to sell?" or "do you
    remember what I told you last time?".

    Args:
        phone: Farmer's 10-digit phone number.

    Returns:
        JSON string with a list of the farmer's open sell intents.
    """
    return _fmt(list_my_intents_tool.invoke({"phone": phone}))


# ---------------------------------------------------------------------------
# TOOL 8 -- get_weather
# ---------------------------------------------------------------------------
@mcp.tool()
def get_weather(latitude: float, longitude: float, days: int = 3) -> str:
    """Fetch a daily weather forecast for a geographic location.

    Returns temperature, weather condition, precipitation, and a
    'safe_to_travel' flag for each day.

    Useful for farmers deciding whether to travel to a mandi.

    Args:
        latitude:  Latitude in decimal degrees (e.g., 18.5204 for Pune).
        longitude: Longitude in decimal degrees (e.g., 73.8567 for Pune).
        days:      Number of days to forecast. Defaults to 3, max around 7.

    Returns:
        JSON string with the per-day weather forecast.
    """
    return _fmt(get_weather_tool.invoke({
        "latitude":  latitude,
        "longitude": longitude,
        "days":      days,
    }))


# ---------------------------------------------------------------------------
# TOOL 9 -- find_mandi_by_name
# ---------------------------------------------------------------------------
@mcp.tool()
def find_mandi_by_name(
    name: str,
    farmer_lat: Optional[float] = None,
    farmer_lon: Optional[float] = None,
    crop: Optional[str] = None,
) -> str:
    """Look up a specific mandi by name (with fuzzy matching for suburbs).

    Returns the canonical mandi name, coordinates, and (optionally) the
    distance from the farmer's location and the current price of a
    specific crop at that mandi.

    Use when the farmer references a specific mandi by name -- e.g.,
    "how far is Chakan mandi?" or "what's the onion price at Pune Manjri?".

    Args:
        name:       Mandi name or suburb (e.g., "Chakan", "Hadapsar",
                    "Pune Manjri").
        farmer_lat: Farmer's latitude, for distance calculation.
        farmer_lon: Farmer's longitude, for distance calculation.
        crop:       Crop name to fetch price for at this mandi.

    Returns:
        JSON string with the matched mandi, distance (if lat/lon given),
        and price (if crop given). If no mandi matches, returns
        {"found": false}.
    """
    args: dict = {"name": name}
    if farmer_lat is not None:
        args["farmer_lat"] = farmer_lat
    if farmer_lon is not None:
        args["farmer_lon"] = farmer_lon
    if crop is not None:
        args["crop"] = crop
    return _fmt(find_mandi_by_name_tool.invoke(args))


# ---------------------------------------------------------------------------
# TOOL 10 -- list_all_crops_near_me
# ---------------------------------------------------------------------------
@mcp.tool()
def list_all_crops_near_me(
    farmer_lat: float,
    farmer_lon: float,
    vehicle: str = "mini_truck",
    radius_km: float = 60,
    quantity_quintals: float = 10,
    phone: Optional[str] = None,
) -> str:
    """List EVERY crop with recent Pune-district prices, one row per crop
    with its best-net-price mandi (given the farmer's location + vehicle).

    Use for broad questions like "what crops are being sold in the mandi
    today?" or "show me all rates near me".

    If phone is provided, the result is PRE-SPLIT into 'your_stock' (crops
    the farmer owns) and 'other_crops' (everything else), which is more
    useful for personalized responses.

    Args:
        farmer_lat:        Farmer's latitude.
        farmer_lon:        Farmer's longitude.
        vehicle:           "tractor_trolley", "mini_truck", or "truck".
                           Defaults to "mini_truck".
        radius_km:         Only consider mandis within this many km.
                           Defaults to 60.
        quantity_quintals: Quintals per crop, for transport cost calc.
                           Defaults to 10.
        phone:             Farmer's phone number. If given, output is
                           split by stock ownership.

    Returns:
        JSON string. If phone given: {your_stock: [...], other_crops: [...]}.
        Otherwise: {crops: [...]}.
    """
    args: dict = {
        "farmer_lat":        farmer_lat,
        "farmer_lon":        farmer_lon,
        "vehicle":           vehicle,
        "radius_km":         radius_km,
        "quantity_quintals": quantity_quintals,
    }
    if phone is not None:
        args["phone"] = phone
    return _fmt(list_all_crops_near_me_tool.invoke(args))


# ---------------------------------------------------------------------------
# TOOL 11 -- list_crops_at_mandi
# ---------------------------------------------------------------------------
@mcp.tool()
def list_crops_at_mandi(
    mandi_name: str,
    farmer_lat: Optional[float] = None,
    farmer_lon: Optional[float] = None,
    on_date: Optional[str] = None,
) -> str:
    """List ALL crops traded at a SPECIFIC mandi, optionally on a
    specific date.

    Use for questions like "what crops are trading at Pune Manjri APMC
    today?" or "what was traded at Chakan yesterday?".

    Args:
        mandi_name: The mandi name (e.g., "Pune(Manjri) APMC", "Chakan").
        farmer_lat: Farmer's latitude, for distance calculation.
        farmer_lon: Farmer's longitude, for distance calculation.
        on_date:    Specific date in DD/MM/YYYY format. If omitted,
                    returns the freshest 7-day window of crops.

    Returns:
        JSON string with all crops trading at that mandi, with modal
        prices and arrival dates.
    """
    args: dict = {"mandi_name": mandi_name}
    if farmer_lat is not None:
        args["farmer_lat"] = farmer_lat
    if farmer_lon is not None:
        args["farmer_lon"] = farmer_lon
    if on_date is not None:
        args["on_date"] = on_date
    return _fmt(list_crops_at_mandi_tool.invoke(args))


# ---------------------------------------------------------------------------
# TOOL 12 -- lookup_scheme_info (RAG)
# ---------------------------------------------------------------------------
@mcp.tool()
def lookup_scheme_info(question: str) -> str:
    """Answer questions about Indian Central Government agricultural schemes.

    Uses a RAG (retrieval-augmented generation) pipeline: retrieves relevant
    chunks from a curated corpus of 5 schemes (PM-Kisan, PMFBY, KCC, MSP,
    Soil Health Card), then generates a grounded answer with source citation.

    Use for questions about:
      * PM-Kisan (income support)
      * PMFBY (crop insurance)
      * KCC (Kisan Credit Card)
      * MSP (Minimum Support Price)
      * Soil Health Card
      * Related topics: eligibility, application, documents, amounts, status.

    Args:
        question: The user's question verbatim (English, Hindi, or Marathi).
                  Do NOT paraphrase.

    Returns:
        A grounded natural-language answer with source citation.
        If the corpus doesn't cover the question, returns a polite refusal.
    """
    return lookup_scheme_info_tool.invoke({"question": question})


# ---------------------------------------------------------------------------
# Entry point -- run the server on stdio transport.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run()
