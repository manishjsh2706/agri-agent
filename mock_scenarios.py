"""Mock scenarios for testing the mandi comparison engine.

Each scenario in SCENARIOS is a dictionary with these keys:

  id                : integer
  name              : short title
  description       : one-line description of what this case tests
  mock_prices       : list of records (same shape as the data.gov.in API)
  mandi_locations   : {market_name: (lat, lon)} for every market mentioned
  farmer            : {"lat": .., "lon": .., "vehicle": ".."}
  alt_farmer        : optional second farmer position (used by scenario 12)
  crop              : the crop the farmer is asking about
  quantity_quintals : how many quintals the farmer has to sell
  radius_km         : the maximum mandi distance to consider
  expected          : what the comparison engine should answer

These scenarios are completely independent of the live data.gov.in API.
They let us verify the agent's behaviour for specific situations on demand,
including situations that may not occur in real data on any given day
(such as a price spike, a stale-data warning, or a vehicle-flip).
"""

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

# Per-kilometre cost (rupees) for each vehicle type the farmer might use.
# The comparison engine will use these for transport-cost calculation.
VEHICLE_RATES = {
    "tractor_trolley":  8,
    "mini_truck":      18,
    "truck":           28,
}

# Dates used in the scenarios.
TODAY      = "25/05/2026"
DAY_3_OLD  = "22/05/2026"
DAY_5_OLD  = "20/05/2026"

# Approximate coordinates for markets in and around Nagpur district.
# (The exact numbers don't need to be perfect, only realistic enough to
# give plausible distances when fed through the haversine formula.)
NAGPUR  = (21.1458, 79.0882)   # central reference point
KAMPTEE = (21.2250, 79.1970)   # ~13 km NE
SAONER  = (21.3800, 78.9100)   # ~28 km N
KATOL   = (21.2650, 78.5830)   # ~52 km NW
RAMTEK  = (21.3960, 79.3280)   # ~38 km NE
WARDHA  = (20.7450, 78.6020)   # ~76 km SW   (outside 50 km radius)


# ---------------------------------------------------------------------------
# Helper to build a price record without typing every field every time.
# ---------------------------------------------------------------------------
def _price(market, commodity, modal,
           *, variety="Local", grade="FAQ",
           min_p=None, max_p=None, arrival=TODAY):
    if isinstance(modal, (int, float)) and modal > 0:
        if min_p is None: min_p = modal - 100
        if max_p is None: max_p = modal + 100
    return {
        "state":        "Maharashtra",
        "district":     "Nagpur",
        "market":       market,
        "commodity":    commodity,
        "variety":      variety,
        "grade":        grade,
        "min_price":    min_p,
        "modal_price":  modal,
        "max_price":    max_p,
        "arrival_date": arrival,
    }


FARMER_NAGPUR  = {"lat": 21.1458, "lon": 79.0882, "vehicle": "mini_truck"}
FARMER_NEAR_WARDHA = {"lat": 20.7450, "lon": 78.6020, "vehicle": "mini_truck"}


# ---------------------------------------------------------------------------
# THE SCENARIOS
# ---------------------------------------------------------------------------
SCENARIOS = [

    # ----- Group 1: core comparison correctness ----------------------------
    {
        "id": 1, "name": "Clear winner",
        "description":
            "Three nearby mandis with clearly different net prices; the "
            "highest-net-price mandi must rank first.",
        "mandi_locations": {"Nagpur": NAGPUR, "Kamptee": KAMPTEE, "Saoner": SAONER},
        "mock_prices": [
            _price("Nagpur",  "Onion", 2400),
            _price("Kamptee", "Onion", 2200),
            _price("Saoner",  "Onion", 2000),
        ],
        "farmer": FARMER_NAGPUR,
        "crop": "Onion", "quantity_quintals": 10, "radius_km": 50,
        "expected": {"top_mandi": "Nagpur"},
    },

    {
        "id": 2, "name": "Transport flips the answer",
        "description":
            "A far mandi has a higher gross price, but the transport cost "
            "makes a nearer mandi win on net price.",
        "mandi_locations": {"Nagpur": NAGPUR, "Ramtek": RAMTEK},
        "mock_prices": [
            _price("Nagpur", "Onion", 2200),   # right next to the farmer
            _price("Ramtek", "Onion", 2400),   # ~38 km away
        ],
        "farmer": {"lat": 21.1458, "lon": 79.0882, "vehicle": "truck"},
        "crop": "Onion", "quantity_quintals": 3, "radius_km": 60,
        "expected": {
            "top_mandi": "Nagpur",
            "reason": "Ramtek's transport cost outweighs its higher gross price.",
        },
    },

    {
        "id": 3, "name": "Tie at the top",
        "description":
            "Two mandis end up with the same net price; both should appear "
            "and the order must be stable across runs.",
        "mandi_locations": {"Nagpur": NAGPUR, "Kamptee": KAMPTEE},
        "mock_prices": [
            _price("Nagpur",  "Wheat", 2300),
            _price("Kamptee", "Wheat", 2300),
        ],
        "farmer": {"lat": 21.1458, "lon": 79.0882, "vehicle": "tractor_trolley"},
        "crop": "Wheat", "quantity_quintals": 10, "radius_km": 50,
        "expected": {"top_mandi_in": ["Nagpur", "Kamptee"]},
    },

    {
        "id": 4, "name": "Outside the 50 km radius",
        "description":
            "A high-price mandi exists but it is more than 50 km away; "
            "it must be excluded from the ranking.",
        "mandi_locations": {"Nagpur": NAGPUR, "Wardha": WARDHA},
        "mock_prices": [
            _price("Nagpur", "Soyabean", 4500),
            _price("Wardha", "Soyabean", 5000),     # ~76 km
        ],
        "farmer": FARMER_NAGPUR,
        "crop": "Soyabean", "quantity_quintals": 8, "radius_km": 50,
        "expected": {"top_mandi": "Nagpur", "must_not_contain": ["Wardha"]},
    },

    # ----- Group 2: edge cases --------------------------------------------
    {
        "id": 5, "name": "Crop not available today",
        "description":
            "None of the nearby mandis reported the farmer's crop today. "
            "The agent must answer gracefully, not crash or invent a number.",
        "mandi_locations": {"Nagpur": NAGPUR, "Kamptee": KAMPTEE},
        "mock_prices": [
            _price("Nagpur",  "Wheat", 2200),
            _price("Kamptee", "Wheat", 2150),
        ],
        "farmer": FARMER_NAGPUR,
        "crop": "Onion", "quantity_quintals": 10, "radius_km": 50,
        "expected": {"no_data_for_crop": True},
    },

    {
        "id": 6, "name": "Only one mandi in range",
        "description":
            "Just one nearby mandi has data for the crop. The engine still "
            "produces an answer; the message must note there is no comparison.",
        "mandi_locations": {"Kamptee": KAMPTEE},
        "mock_prices": [_price("Kamptee", "Tomato", 1800)],
        "farmer": {"lat": 21.1458, "lon": 79.0882, "vehicle": "tractor_trolley"},
        "crop": "Tomato", "quantity_quintals": 4, "radius_km": 50,
        "expected": {"top_mandi": "Kamptee", "single_mandi": True},
    },

    {
        "id": 7, "name": "Mixed freshness",
        "description":
            "Some mandis reported today, others three days ago. The engine "
            "should use the latest available per mandi and flag the dates.",
        "mandi_locations": {"Nagpur": NAGPUR, "Saoner": SAONER, "Kamptee": KAMPTEE},
        "mock_prices": [
            _price("Nagpur",  "Onion", 2400, arrival=TODAY),
            _price("Saoner",  "Onion", 2350, arrival=DAY_3_OLD),
            _price("Kamptee", "Onion", 2300, arrival=TODAY),
        ],
        "farmer": FARMER_NAGPUR,
        "crop": "Onion", "quantity_quintals": 10, "radius_km": 50,
        "expected": {"top_mandi": "Nagpur", "freshness_warning_for": ["Saoner"]},
    },

    {
        "id": 8, "name": "All data is stale",
        "description":
            "Every nearby mandi reported 5+ days ago. The answer must loudly "
            "flag low confidence rather than pretending the data is current.",
        "mandi_locations": {"Nagpur": NAGPUR, "Saoner": SAONER},
        "mock_prices": [
            _price("Nagpur", "Onion", 2400, arrival=DAY_5_OLD),
            _price("Saoner", "Onion", 2300, arrival=DAY_5_OLD),
        ],
        "farmer": FARMER_NAGPUR,
        "crop": "Onion", "quantity_quintals": 10, "radius_km": 50,
        "expected": {"top_mandi": "Nagpur", "low_confidence": True},
    },

    # ----- Group 3: data quality ------------------------------------------
    {
        "id": 9, "name": "Bad rows in the data",
        "description":
            "Records with a zero or missing modal price must be skipped "
            "(not poison the ranking).",
        "mandi_locations": {"Nagpur": NAGPUR, "Kamptee": KAMPTEE, "Saoner": SAONER},
        "mock_prices": [
            _price("Nagpur",  "Onion", 2400),
            _price("Kamptee", "Onion", 0),         # bad row: zero
            _price("Saoner",  "Onion", None),      # bad row: missing
        ],
        "farmer": FARMER_NAGPUR,
        "crop": "Onion", "quantity_quintals": 10, "radius_km": 50,
        "expected": {"top_mandi": "Nagpur",
                     "bad_rows_skipped": ["Kamptee", "Saoner"]},
    },

    {
        "id": 10, "name": "Commodity spelling variants",
        "description":
            "The farmer searches as 'soybean' but the data spells it "
            "'Soyabean'. Case-insensitive matching with aliases must still find it.",
        "mandi_locations": {"Nagpur": NAGPUR, "Saoner": SAONER},
        "mock_prices": [
            _price("Nagpur", "Soyabean", 4400),
            _price("Saoner", "Soyabean", 4300),
        ],
        "farmer": FARMER_NAGPUR,
        "crop": "soybean", "quantity_quintals": 12, "radius_km": 50,
        "expected": {"top_mandi": "Nagpur"},
    },

    # ----- Group 4: farmer-side realism -----------------------------------
    {
        "id": 11, "name": "Vehicle changes the ranking",
        "description":
            "Same prices, same mandis, same farmer location -- but a more "
            "expensive vehicle (per km) can flip which mandi wins on net price.",
        "mandi_locations": {"Nagpur": NAGPUR, "Ramtek": RAMTEK},
        "mock_prices": [
            _price("Nagpur", "Wheat", 2300),
            _price("Ramtek", "Wheat", 2440),
        ],
        # The engine should be run twice for this scenario, once per vehicle.
        "farmer": {"lat": 21.1458, "lon": 79.0882, "vehicle": "truck"},
        "alt_vehicles": ["truck", "tractor_trolley"],
        "crop": "Wheat", "quantity_quintals": 3, "radius_km": 60,
        "expected": {
            "with_truck_top_mandi": "Nagpur",
            "with_tractor_trolley_top_mandi": "Ramtek",
        },
    },

    {
        "id": 12, "name": "Farmer location matters",
        "description":
            "Move the farmer ~75 km to the south-west and the set of nearby "
            "mandis (and therefore the best answer) should change.",
        "mandi_locations": {"Nagpur": NAGPUR, "Saoner": SAONER, "Wardha": WARDHA},
        "mock_prices": [
            _price("Nagpur",  "Onion", 2300),
            _price("Saoner",  "Onion", 2400),
            _price("Wardha",  "Onion", 2500),
        ],
        "farmer":     FARMER_NAGPUR,
        "alt_farmer": FARMER_NEAR_WARDHA,
        "crop": "Onion", "quantity_quintals": 10, "radius_km": 50,
        "expected": {
            "from_nagpur_top_mandi": "Saoner",
            "from_wardha_top_mandi": "Wardha",
        },
    },
]


if __name__ == "__main__":
    # Light sanity print so `python mock_scenarios.py` shows something useful.
    print(f"Loaded {len(SCENARIOS)} scenarios:")
    for s in SCENARIOS:
        print(f"  {s['id']:>2}. {s['name']}")
