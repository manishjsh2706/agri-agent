"""Synthetic price histories for developing and testing the forecast engine.

WHY THIS EXISTS
---------------
Stage C (forecasting) needs price history to learn from. Today our real
database has only a few weeks of data. So we generate KNOWN-PATTERN
synthetic histories here -- rising trends, falling trends, flat, weekly
seasonality, sudden spikes -- so we can verify the forecast models
behave sensibly before pointing them at real data.

Once a few months of real data have accumulated, the same forecast
functions work on real data without any change.

Public functions
----------------
    linear_rising(start_price, days, slope, noise, seed)  -> list[(date, price)]
    linear_falling(...)
    flat(...)
    weekly_seasonal(...)
    spike_then_recover(...)
    real_world_mix(...)     -- combines trend + seasonality + noise

Each returns a list of (date_str, modal_price) tuples sorted oldest-first.
"""

import math
import random
from datetime import date, timedelta

DEFAULT_END_DATE = date(2026, 6, 21)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _dates(n_days: int, end: date = DEFAULT_END_DATE) -> list[str]:
    """Generate n_days dates ending on `end` (oldest-first), as DD/MM/YYYY."""
    return [(end - timedelta(days=n_days - 1 - i)).strftime("%d/%m/%Y")
            for i in range(n_days)]


def _noise(noise: float, rng: random.Random) -> float:
    return rng.gauss(0, noise)


def _pack(dates: list[str], prices: list[float]) -> list[tuple[str, float]]:
    return [(d, round(p, 2)) for d, p in zip(dates, prices)]


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------
def linear_rising(
    start_price: float = 1500,
    days: int = 60,
    slope: float = 8.0,         # rupees added per day
    noise: float = 30.0,
    seed: int = 1,
) -> list[tuple[str, float]]:
    """Prices that drift upward over time + Gaussian noise."""
    rng = random.Random(seed)
    prices = [start_price + slope * i + _noise(noise, rng) for i in range(days)]
    return _pack(_dates(days), prices)


def linear_falling(
    start_price: float = 2500,
    days: int = 60,
    slope: float = 6.0,
    noise: float = 30.0,
    seed: int = 2,
) -> list[tuple[str, float]]:
    """Prices that drift downward + noise. (slope is the daily drop magnitude.)"""
    rng = random.Random(seed)
    prices = [start_price - slope * i + _noise(noise, rng) for i in range(days)]
    return _pack(_dates(days), prices)


def flat(
    price: float = 2000,
    days: int = 60,
    noise: float = 40.0,
    seed: int = 3,
) -> list[tuple[str, float]]:
    """Stationary series. Good null hypothesis."""
    rng = random.Random(seed)
    prices = [price + _noise(noise, rng) for _ in range(days)]
    return _pack(_dates(days), prices)


def weekly_seasonal(
    base_price: float = 2000,
    days: int = 60,
    amp: float = 120.0,
    noise: float = 30.0,
    seed: int = 4,
) -> list[tuple[str, float]]:
    """7-day sinusoidal seasonality on top of a flat trend."""
    rng = random.Random(seed)
    prices = [
        base_price + amp * math.sin(2 * math.pi * (i % 7) / 7) + _noise(noise, rng)
        for i in range(days)
    ]
    return _pack(_dates(days), prices)


def spike_then_recover(
    base_price: float = 1800,
    spike: float = 800,
    spike_day: int = 30,
    spike_width: int = 4,
    days: int = 60,
    noise: float = 30.0,
    seed: int = 5,
) -> list[tuple[str, float]]:
    """Flat-ish baseline with a temporary supply-shock-like spike."""
    rng = random.Random(seed)
    prices = []
    for i in range(days):
        bump = 0.0
        if 0 <= (i - spike_day) <= spike_width:
            bump = spike * (1 - (i - spike_day) / spike_width)
        prices.append(base_price + bump + _noise(noise, rng))
    return _pack(_dates(days), prices)


def real_world_mix(
    start_price: float = 1800,
    days: int = 60,
    drift: float = 4.0,         # gentle rising drift
    seasonal_amp: float = 80.0, # weekly seasonality amplitude
    noise: float = 35.0,
    seed: int = 6,
) -> list[tuple[str, float]]:
    """Trend + weekly seasonality + noise. Closest to a real Pune mandi."""
    rng = random.Random(seed)
    prices = []
    for i in range(days):
        trend     = start_price + drift * i
        seasonal  = seasonal_amp * math.sin(2 * math.pi * (i % 7) / 7)
        prices.append(trend + seasonal + _noise(noise, rng))
    return _pack(_dates(days), prices)


# ---------------------------------------------------------------------------
# Convenience: a small named bundle for tests / leaderboard
# ---------------------------------------------------------------------------
ALL_HISTORIES = {
    "rising":             linear_rising(),
    "falling":            linear_falling(),
    "flat":               flat(),
    "weekly_seasonal":    weekly_seasonal(),
    "spike_then_recover": spike_then_recover(),
    "real_world_mix":     real_world_mix(),
}


if __name__ == "__main__":
    for name, h in ALL_HISTORIES.items():
        first = h[0][1]
        last  = h[-1][1]
        print(f"  {name:<22} {len(h)} days   "
              f"first Rs {first:>6.0f}   last Rs {last:>6.0f}")
