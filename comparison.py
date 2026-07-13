"""Mandi comparison engine.

Pure-function module. Given a list of price records, mandi coordinates,
the farmer's location, vehicle and quantity, it returns a ranked answer:
which mandi gives the best net price (modal price minus transport cost
per quintal), within the chosen radius.

NO API CALLS. NO DATABASE. NO AI.  Just maths and rules.

Public entry point
------------------
    compare_mandis(prices, mandi_locations,
                   farmer_lat, farmer_lon, vehicle, crop,
                   *, radius_km=50, quantity_quintals=10, today=None)

Returns a dict like:

    {
      "top_mandi":            "Nagpur",
      "ranking":              [ {market, gross_modal_price, distance_km,
                                 transport_cost_total, transport_cost_per_quintal,
                                 net_price_per_quintal, arrival_date,
                                 days_old, is_stale}, ... ],
      "no_data_for_crop":     False,
      "single_mandi":         False,
      "low_confidence":       False,   # True when every kept mandi is stale
      "freshness_warning_for": [],     # markets with stale data
      "bad_rows_skipped":     [],      # markets whose row had bad prices
      "excluded_for_radius":  [],      # markets dropped for being too far
    }
"""

import math
from datetime import date, datetime


# -- Configuration ---------------------------------------------------------

# Per-kilometre cost (rupees) for each vehicle type. Same values as
# mock_scenarios.py; kept here as a constant the engine relies on.
VEHICLE_RATES = {
    "tractor_trolley":  8,
    "mini_truck":      18,
    "truck":           28,
}

# Anything older than this number of days is treated as "stale" data.
STALENESS_THRESHOLD_DAYS = 2

# Commodity name normalisation. Real data uses spellings like 'Soyabean';
# farmers may type 'soybean'. Add aliases here as you encounter them.
COMMODITY_ALIASES = {
    "soybean": "soyabean",
    "soya":    "soyabean",
    "tur":     "arhar (tur/red gram)(whole)",
    "arhar":   "arhar (tur/red gram)(whole)",
    "kanda":   "onion",
}


# -- Small helpers ---------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two lat/lon points."""
    R = 6371.0088  # mean Earth radius, km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _norm_commodity(name: str) -> str:
    """Lowercase + alias-map a commodity name."""
    if name is None:
        return ""
    s = str(name).strip().lower()
    return COMMODITY_ALIASES.get(s, s)


def _parse_date(s):
    """Parse a 'DD/MM/YYYY' arrival date. Returns a date or None."""
    if not s:
        return None
    try:
        return datetime.strptime(str(s).strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _is_valid_price(v) -> bool:
    return isinstance(v, (int, float)) and v > 0


# -- The engine -----------------------------------------------------------

def compare_mandis(
    prices,
    mandi_locations,
    farmer_lat: float,
    farmer_lon: float,
    vehicle: str,
    crop: str,
    *,
    radius_km: float = 50,
    quantity_quintals: float = 10,
    today=None,
):
    """Rank mandis for one crop by net price (modal - transport per quintal).

    All filtering, ranking and freshness logic lives here. Inputs are plain
    data; outputs are a plain dict (see the module docstring).
    """

    # --- Setup ----------------------------------------------------------
    if today is None:
        today = date.today()
    elif isinstance(today, str):
        today = _parse_date(today) or date.today()

    if vehicle not in VEHICLE_RATES:
        raise ValueError(
            f"Unknown vehicle '{vehicle}'. Known: {list(VEHICLE_RATES)}"
        )
    rate = VEHICLE_RATES[vehicle]

    target_crop = _norm_commodity(crop)

    empty_result = {
        "top_mandi":             None,
        "ranking":               [],
        "no_data_for_crop":      False,
        "single_mandi":          False,
        "low_confidence":        False,
        "freshness_warning_for": [],
        "bad_rows_skipped":      [],
        "excluded_for_radius":   [],
    }

    # --- 1. Keep only rows whose commodity matches ----------------------
    crop_rows = [
        r for r in prices
        if _norm_commodity(r.get("commodity", "")) == target_crop
    ]
    if not crop_rows:
        return {**empty_result, "no_data_for_crop": True}

    # --- 2. Split good rows from bad rows -------------------------------
    bad_rows_skipped, good_rows = [], []
    for r in crop_rows:
        if _is_valid_price(r.get("modal_price")):
            good_rows.append(r)
        else:
            bad_rows_skipped.append(r.get("market", "?"))

    # --- 3. For each market, take the newest valid row within radius ----
    excluded_for_radius = []
    by_market = {}                                # market -> chosen row
    for r in good_rows:
        market = r.get("market", "")
        if market not in mandi_locations:
            continue                              # unknown market location
        m_lat, m_lon = mandi_locations[market]
        distance_km = haversine_km(farmer_lat, farmer_lon, m_lat, m_lon)
        if distance_km > radius_km:
            excluded_for_radius.append(market)
            continue
        prior = by_market.get(market)
        r_date = _parse_date(r.get("arrival_date"))
        p_date = _parse_date(prior.get("arrival_date")) if prior else None
        if not prior or (r_date and (not p_date or r_date > p_date)):
            by_market[market] = {**r, "_distance_km": distance_km}

    if not by_market:
        return {
            **empty_result,
            "bad_rows_skipped":    sorted(set(bad_rows_skipped)),
            "excluded_for_radius": sorted(set(excluded_for_radius)),
        }

    # --- 4. Compute net price, freshness; build ranking -----------------
    ranking = []
    freshness_warning_for = []
    for market, r in by_market.items():
        distance_km     = r["_distance_km"]
        transport_total = distance_km * rate
        transport_per_q = transport_total / quantity_quintals
        modal           = float(r["modal_price"])
        net_price       = modal - transport_per_q

        arrival        = r.get("arrival_date", "")
        arrival_date   = _parse_date(arrival)
        days_old       = (today - arrival_date).days if arrival_date else None
        is_stale       = days_old is not None and days_old > STALENESS_THRESHOLD_DAYS
        if is_stale:
            freshness_warning_for.append(market)

        ranking.append({
            "market":                     market,
            "gross_modal_price":          modal,
            "distance_km":                round(distance_km, 1),
            "transport_cost_total":       round(transport_total, 1),
            "transport_cost_per_quintal": round(transport_per_q, 2),
            "net_price_per_quintal":      round(net_price, 2),
            "arrival_date":               arrival,
            "days_old":                   days_old,
            "is_stale":                   is_stale,
        })

    # --- 5. Sort: highest net price first; stable by market name --------
    ranking.sort(key=lambda it: (-it["net_price_per_quintal"], it["market"]))

    low_confidence = all(it["is_stale"] for it in ranking)

    return {
        "top_mandi":             ranking[0]["market"],
        "ranking":               ranking,
        "no_data_for_crop":      False,
        "single_mandi":          len(ranking) == 1,
        "low_confidence":        low_confidence,
        "freshness_warning_for": sorted(set(freshness_warning_for)),
        "bad_rows_skipped":      sorted(set(bad_rows_skipped)),
        "excluded_for_radius":   sorted(set(excluded_for_radius)),
    }
