"""Lat / lon lookup for the main mandis in Pune district.

Also provides find_mandi_by_name() so the LLM agent can resolve names
like "Hadapsar" (a Pune suburb served by Pune(Manjri) APMC).
"""

from __future__ import annotations

import difflib
from typing import Optional

PUNE_MANDIS = {
    # ---- City-area mandis -----------------------------------------------
    "Pune":                  (18.4956, 73.8588),
    "Pune(Khadiki)":         (18.5670, 73.8740),
    "Pune(Manjri)":          (18.4720, 73.9220),
    "Pune(Moshi)":           (18.6650, 73.8410),
    "Pune(Pimpri)":          (18.6298, 73.7997),
    "Pimpri":                (18.6298, 73.7997),

    # ---- North & north-east --------------------------------------------
    "Khed":                  (18.8451, 73.9008),
    "Khed(Chakan)":          (18.7600, 73.8429),
    "Chakan":                (18.7600, 73.8429),
    "Manchar":               (19.0001, 73.9436),
    "Junnar":                (19.2050, 73.8779),
    "Junnar(Narayangaon)":   (19.0850, 73.9450),
    "Junnar(Otur)":          (19.1700, 73.9290),
    "Junnar(Alephata)":      (19.2640, 73.9870),
    "Shirur":                (18.8281, 74.3781),

    # ---- West-side mandis ----------------------------------------------
    "Talegaon":              (18.7322, 73.6724),

    # ---- South & south-east --------------------------------------------
    "Bhor":                  (18.1500, 73.8500),
    "Saswad":                (18.3437, 74.0317),
    "Baramati":              (18.1514, 74.5800),
    "Indapur":               (18.1167, 75.0167),
    "Indapur(Bhigwan)":      (18.2900, 74.7670),
    "Indapur(Nimgaon Ketki)":(18.0917, 74.8470),
    "Daund":                 (18.4639, 74.5786),
}

# Auto-alias every entry with " APMC" suffix (the API often appends it).
for _name in list(PUNE_MANDIS.keys()):
    PUNE_MANDIS.setdefault(f"{_name} APMC", PUNE_MANDIS[_name])


# ---------------------------------------------------------------------------
# AREA_HINTS -- suburbs / neighbourhoods -> the actual mandi that serves them
# ---------------------------------------------------------------------------
AREA_HINTS: dict[str, str] = {
    "hadapsar":         "Pune(Manjri)",
    "manjari":          "Pune(Manjri)",
    "manjri":           "Pune(Manjri)",
    "gultekdi":         "Pune",
    "market yard":      "Pune",
    "kothrud":          "Pune",
    "shivajinagar":     "Pune",
    "pune apmc":        "Pune",
    "pune market":      "Pune",
    "khadki":           "Pune(Khadiki)",
    "khadiki":          "Pune(Khadiki)",
    "moshi":            "Pune(Moshi)",
    "pimpri chinchwad": "Pimpri",
    "pcmc":             "Pimpri",
    "chakan":           "Chakan",
    "narayangaon":      "Junnar(Narayangaon)",
    "otur":             "Junnar(Otur)",
    "alephata":         "Junnar(Alephata)",
    "bhigwan":          "Indapur(Bhigwan)",
    "nimgaon ketki":    "Indapur(Nimgaon Ketki)",
}


def _canonical_keys() -> list[str]:
    """Unique canonical mandi names (strip the ' APMC' auto-aliases)."""
    seen: list[str] = []
    for k in PUNE_MANDIS.keys():
        base = k.replace(" APMC", "")
        if base not in seen:
            seen.append(base)
    return seen


def find_mandi_by_name(name: str) -> Optional[dict]:
    """Look up a Pune mandi by name / nickname / suburb.

    Strategy: exact -> area hint -> substring -> difflib fuzzy.
    Returns None if nothing matches with reasonable confidence.
    """
    if not name or not name.strip():
        return None

    q = name.strip().lower()

    # 1. Exact match
    for key in PUNE_MANDIS.keys():
        if key.lower() == q or key.replace(" APMC", "").lower() == q:
            lat, lon = PUNE_MANDIS[key]
            return {
                "matched_name": key.replace(" APMC", ""),
                "latitude":     lat,
                "longitude":    lon,
                "match_type":   "exact",
                "query":        name,
            }

    # Strip trailing 'mandi' / 'apmc' / 'market' / 'bazaar' before further tries
    trimmed = q
    for suffix in (" mandi", " apmc", " market", " bazaar"):
        if trimmed.endswith(suffix):
            trimmed = trimmed[: -len(suffix)].strip()

    # 2. Area hint
    if trimmed in AREA_HINTS:
        canonical = AREA_HINTS[trimmed]
        lat, lon = PUNE_MANDIS[canonical]
        return {
            "matched_name": canonical,
            "latitude":     lat,
            "longitude":    lon,
            "match_type":   "area_hint",
            "query":        name,
        }

    # 3. Substring
    for key in _canonical_keys():
        if trimmed and trimmed in key.lower():
            lat, lon = PUNE_MANDIS[key]
            return {
                "matched_name": key,
                "latitude":     lat,
                "longitude":    lon,
                "match_type":   "substring",
                "query":        name,
            }

    # 4. Fuzzy
    candidates = _canonical_keys() + list(AREA_HINTS.keys())
    close = difflib.get_close_matches(
        trimmed, [c.lower() for c in candidates], n=1, cutoff=0.6
    )
    if close:
        hit = close[0]
        canonical = None
        for c in _canonical_keys():
            if c.lower() == hit:
                canonical = c
                break
        if canonical is None and hit in AREA_HINTS:
            canonical = AREA_HINTS[hit]
        if canonical:
            lat, lon = PUNE_MANDIS[canonical]
            return {
                "matched_name": canonical,
                "latitude":     lat,
                "longitude":    lon,
                "match_type":   "fuzzy",
                "query":        name,
            }

    return None
