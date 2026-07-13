"""Stage D.2 -- weather forecast helper (Open-Meteo).

WHY THIS EXISTS
---------------
So the agent can warn a farmer before a planned mandi trip. Example:
"Rain heavy tomorrow (32 mm) -- go Wednesday instead."

WHY OPEN-METEO
--------------
Free, no API key, generous rate limits, worldwide coverage, honest
weather-code taxonomy from WMO. Perfect for a project like this.

Public function
---------------
    get_daily_forecast(lat, lon, days=3) -> list[dict]

Each dict has:
    date              (YYYY-MM-DD)
    temp_max_c        max temperature that day, degrees Celsius
    temp_min_c        min temperature that day
    precipitation_mm  total rainfall (or 0.0)
    weather_code      raw WMO code
    weather           human name of the weather (e.g. "Moderate rain")
    safe_to_travel    "yes" / "caution_rain" / "no_heavy_rain" /
                      "no_thunderstorm" / "caution_heat"
"""

from __future__ import annotations

import sys

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes we care about (small subset -- Open-Meteo lists many).
WEATHER_CODE_NAMES: dict[int, str] = {
    0:  "Clear sky",
    1:  "Mainly clear",  2:  "Partly cloudy",  3:  "Overcast",
    45: "Fog",           48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Light rain",    63: "Moderate rain",    65: "Heavy rain",
    71: "Light snow",    73: "Moderate snow",    75: "Heavy snow",
    80: "Rain showers, slight", 81: "Rain showers, moderate",
    82: "Rain showers, violent",
    95: "Thunderstorm",  96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _safe_to_travel(precip_mm: float | None,
                    temp_max_c: float | None,
                    code: int | None) -> str:
    """A simple, honest rule of thumb -- not a full meteorological model."""
    if code is not None and code >= 95:
        return "no_thunderstorm"
    p = precip_mm or 0.0
    if p > 25:
        return "no_heavy_rain"
    if p > 10:
        return "caution_rain"
    if (temp_max_c or 0) > 42:
        return "caution_heat"
    return "yes"


def get_daily_forecast(
    lat: float,
    lon: float,
    days: int = 3,
    timeout: float = 15,
) -> list[dict]:
    """Fetch and shape the next `days` days of forecast.

    Returns a list oldest-first (today, tomorrow, ...).
    Raises an exception if the API call fails."""
    days = max(1, min(int(days), 14))
    params = {
        "latitude":       float(lat),
        "longitude":      float(lon),
        "daily":          "temperature_2m_max,temperature_2m_min,"
                          "precipitation_sum,weather_code",
        "timezone":       "Asia/Kolkata",
        "forecast_days":  days,
    }
    r = requests.get(OPEN_METEO_URL, params=params, timeout=timeout)
    r.raise_for_status()
    d = (r.json() or {}).get("daily", {}) or {}

    dates  = d.get("time", []) or []
    tmax   = d.get("temperature_2m_max", []) or []
    tmin   = d.get("temperature_2m_min", []) or []
    precip = d.get("precipitation_sum", []) or []
    codes  = d.get("weather_code", []) or []

    out: list[dict] = []
    for i, date in enumerate(dates):
        code = codes[i] if i < len(codes) else None
        pmax = tmax[i]  if i < len(tmax)  else None
        pmin = tmin[i]  if i < len(tmin)  else None
        pmm  = precip[i] if i < len(precip) else None
        out.append({
            "date":             date,
            "temp_max_c":       pmax,
            "temp_min_c":       pmin,
            "precipitation_mm": pmm,
            "weather_code":     code,
            "weather":          WEATHER_CODE_NAMES.get(code, "Unknown"),
            "safe_to_travel":   _safe_to_travel(pmm, pmax, code),
        })
    return out


if __name__ == "__main__":
    # Quick demo: Pune next 3 days.
    forecast = get_daily_forecast(18.5089, 73.9259, days=3)
    for f in forecast:
        print(f"{f['date']}  {f['weather']:<26}  "
              f"{f['temp_min_c']}-{f['temp_max_c']}°C  "
              f"rain={f['precipitation_mm']}mm  "
              f"travel={f['safe_to_travel']}")
