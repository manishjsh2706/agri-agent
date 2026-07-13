"""Stage C: price forecasting (the ML layer).

Models implemented
------------------
   naive             : tomorrow == today
   moving_average    : mean of the last N days
   seasonal_naive    : tomorrow == same weekday last week
   holt_winters      : exponential smoothing with trend + seasonality (statsmodels)
   ml_ridge          : scikit-learn Ridge regression with engineered features
                       (lag features, day-of-week, day-of-month, rolling stats)

All models share the same signature:

    forecast(history, days_ahead=7) -> list[float]

where `history` is a list of (date_str, price) tuples, oldest-first.

Use `MODELS` (a dict mapping name -> function) to iterate over them.
Use `forecast_with(model_name, history, days_ahead)` to call by name.

This module is intentionally pure logic. No database, no API, no AI tool calls.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

# scikit-learn and statsmodels are imported lazily so the file still loads
# even if one of them is missing -- the missing model will just raise a
# friendly error if called.
try:
    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False

try:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    _HAS_STATSMODELS = True
except ImportError:
    _HAS_STATSMODELS = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_date(s: str):
    return datetime.strptime(s.strip(), "%d/%m/%Y").date()


def _prices(history) -> list[float]:
    return [float(p) for _, p in history]


def _last_date(history):
    return _parse_date(history[-1][0])


# ---------------------------------------------------------------------------
# Baselines (the "honesty" tier -- any real model must beat these)
# ---------------------------------------------------------------------------
def naive(history, days_ahead: int = 7) -> list[float]:
    """Tomorrow == today. The dumbest reasonable baseline."""
    if not history:
        raise ValueError("empty history")
    return [_prices(history)[-1]] * days_ahead


def moving_average(history, days_ahead: int = 7, window: int = 7) -> list[float]:
    """Forecast = mean of the last `window` prices, repeated."""
    p = _prices(history)
    if not p:
        raise ValueError("empty history")
    window = min(window, len(p))
    avg = sum(p[-window:]) / window
    return [avg] * days_ahead


def seasonal_naive(history, days_ahead: int = 7, period: int = 7) -> list[float]:
    """Forecast for day t+k = price at day t+k-period (e.g. same weekday last week)."""
    p = _prices(history)
    if len(p) < period:
        return moving_average(history, days_ahead)
    return [p[-period + (k % period)] for k in range(days_ahead)]


# ---------------------------------------------------------------------------
# Statistical: Holt-Winters exponential smoothing
# ---------------------------------------------------------------------------
def holt_winters(history, days_ahead: int = 7, period: int = 7) -> list[float]:
    """Triple exponential smoothing: trend + seasonality + level.

    Falls back to moving_average if statsmodels isn't installed or if the
    series is too short for Holt-Winters to fit.
    """
    if not _HAS_STATSMODELS:
        return moving_average(history, days_ahead)
    p = _prices(history)
    if len(p) < 2 * period:
        return moving_average(history, days_ahead)
    try:
        model = ExponentialSmoothing(
            p, trend="add", seasonal="add",
            seasonal_periods=period, initialization_method="estimated",
        ).fit(optimized=True)
        fcast = model.forecast(days_ahead)
        return [float(x) for x in fcast]
    except Exception:
        return moving_average(history, days_ahead)


# ---------------------------------------------------------------------------
# Machine learning: scikit-learn Ridge with engineered features
# ---------------------------------------------------------------------------
def _features(history, target_idx: int, lags: int = 7) -> list[float] | None:
    """Build a feature row for predicting the price at history[target_idx].

    Features:
       - lag_1 .. lag_L     : the last L observed prices
       - rolling_mean_7     : mean of the last 7
       - rolling_std_7      : std of the last 7 (volatility)
       - day_of_week        : 0..6 (sin/cos encoded so the model sees cyclic)
       - day_of_month       : 1..31 (normalised)
       - t                  : linear time index
    """
    if target_idx < lags:
        return None
    p = _prices(history)
    window = p[target_idx - lags : target_idx]    # length L, oldest..yesterday
    last7  = p[max(0, target_idx - 7) : target_idx]
    rolling_mean = sum(last7) / len(last7)
    if len(last7) > 1:
        m = rolling_mean
        rolling_std = math.sqrt(sum((x - m) ** 2 for x in last7) / len(last7))
    else:
        rolling_std = 0.0

    d = _parse_date(history[target_idx][0])
    dow = d.weekday()                  # 0..6
    dow_sin = math.sin(2 * math.pi * dow / 7)
    dow_cos = math.cos(2 * math.pi * dow / 7)
    dom = d.day / 31.0

    return list(window) + [rolling_mean, rolling_std, dow_sin, dow_cos, dom, float(target_idx)]


def ml_ridge(history, days_ahead: int = 7, lags: int = 7,
             alpha: float = 1.0) -> list[float]:
    """Ridge regression on engineered features, recursive multi-step forecast.

    For each future day, we (1) build the feature row using the most recent
    observed + already-forecasted values, (2) predict, (3) append the
    prediction as the next 'observed' value, and repeat.
    """
    if not _HAS_SKLEARN:
        return moving_average(history, days_ahead)
    p = _prices(history)
    if len(p) < lags + 5:
        return moving_average(history, days_ahead)

    # Build training matrix.
    X, y = [], []
    for i in range(lags, len(history)):
        row = _features(history, i, lags=lags)
        if row is None:
            continue
        X.append(row)
        y.append(p[i])
    if len(X) < 5:
        return moving_average(history, days_ahead)

    X = np.array(X)
    y = np.array(y)
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    model = Ridge(alpha=alpha)
    model.fit(Xs, y)

    # Recursive multi-step forecast.
    work = list(history)
    forecasts: list[float] = []
    last_date = _last_date(work)
    for step in range(days_ahead):
        new_date = (last_date + timedelta(days=step + 1)).strftime("%d/%m/%Y")
        work.append((new_date, 0.0))  # placeholder, gets overwritten
        row = _features(work, len(work) - 1, lags=lags)
        if row is None:
            forecasts.append(work[-2][1])
            work[-1] = (new_date, forecasts[-1])
            continue
        row_s = scaler.transform(np.array([row]))
        yhat = float(model.predict(row_s)[0])
        forecasts.append(yhat)
        work[-1] = (new_date, yhat)
    return forecasts


# ---------------------------------------------------------------------------
# Registry + dispatcher
# ---------------------------------------------------------------------------
MODELS = {
    "naive":              naive,
    "moving_avg_7":       lambda h, d=7: moving_average(h, d, window=7),
    "moving_avg_14":      lambda h, d=7: moving_average(h, d, window=14),
    "seasonal_naive_7":   lambda h, d=7: seasonal_naive(h, d, period=7),
    "holt_winters":       holt_winters,
    "ml_ridge":           ml_ridge,
}


def forecast_with(model_name: str, history, days_ahead: int = 7) -> list[float]:
    """Call a named model from the MODELS registry."""
    if model_name not in MODELS:
        raise ValueError(f"unknown model '{model_name}'. "
                         f"Known: {list(MODELS)}")
    return MODELS[model_name](history, days_ahead)


def forecast(history, days_ahead: int = 7, model: str = "ml_ridge") -> list[float]:
    """Top-level convenience: default to ml_ridge but accept any model name."""
    return forecast_with(model, history, days_ahead)
