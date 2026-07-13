"""Stage C.2 -- 'should the farmer sell today or wait?'

Uses any forecast model from forecast.py to look N days ahead, find the
day with the highest expected NET price (after transport), and decide
whether selling today or waiting is the better call.

Public function
---------------
    best_window(history, days_ahead=7, model='ml_ridge',
                today_net_price=None, threshold_pct=2.0)

Returns:
    {
        "action":            "sell_today" | "wait" | "indifferent",
        "best_day_index":    0..days_ahead   (0 means today)
        "best_day_date":     "DD/MM/YYYY"
        "expected_price":    rupees per quintal
        "gain_vs_today":     rupees per quintal (signed)
        "gain_vs_today_pct": float
        "confidence":        "low" | "medium" | "high"
        "forecast":          [floats]   # the full forecast trajectory
        "model":             model name used
    }

Decision logic
--------------
* If the best expected day is TODAY (index 0) -> "sell_today".
* Else if the best expected day's gain over today is BELOW threshold_pct
  -> "indifferent" (forecast isn't confident enough to recommend waiting).
* Else -> "wait", with best_day_index showing how many days to wait.

Confidence is a simple heuristic:
    high   : > 60 days of history AND |gain_pct| > 3 * threshold
    low    : < 21 days of history OR  |gain_pct| < threshold
    medium : otherwise
"""

from __future__ import annotations

from datetime import datetime, timedelta

from forecast import forecast_with


def _parse(s: str):
    return datetime.strptime(s.strip(), "%d/%m/%Y").date()


def best_window(
    history,
    days_ahead: int = 7,
    model: str = "ml_ridge",
    today_net_price: float | None = None,
    threshold_pct: float = 2.0,
) -> dict:
    """See module docstring."""
    if not history:
        raise ValueError("empty history")

    todays_price = float(history[-1][1]) if today_net_price is None else float(today_net_price)
    last_date    = _parse(history[-1][0])

    fc = forecast_with(model, history, days_ahead)
    # Build a comparison list: index 0 == today's KNOWN price,
    # indices 1..days_ahead == forecasted future days.
    series = [todays_price] + list(fc)

    # Pick the highest-expected-price day.
    best_idx = 0
    best_val = series[0]
    for i, v in enumerate(series):
        if v > best_val:
            best_val = v
            best_idx = i

    gain      = best_val - todays_price
    gain_pct  = (gain / todays_price * 100) if todays_price else 0.0
    best_date = (last_date + timedelta(days=best_idx)).strftime("%d/%m/%Y")

    # Confidence heuristic.
    n = len(history)
    abs_gain_pct = abs(gain_pct)
    if n < 21 or abs_gain_pct < threshold_pct:
        confidence = "low"
    elif n >= 60 and abs_gain_pct >= 3 * threshold_pct:
        confidence = "high"
    else:
        confidence = "medium"

    # Action decision.
    if best_idx == 0:
        action = "sell_today"
    elif abs_gain_pct < threshold_pct:
        action = "indifferent"
    else:
        action = "wait"

    return {
        "action":             action,
        "best_day_index":     best_idx,
        "best_day_date":      best_date,
        "expected_price":     round(best_val, 2),
        "todays_price":       round(todays_price, 2),
        "gain_vs_today":      round(gain, 2),
        "gain_vs_today_pct":  round(gain_pct, 2),
        "confidence":         confidence,
        "forecast":           [round(x, 2) for x in fc],
        "model":              model,
    }


# ---------------------------------------------------------------------------
# Quick demo when run directly
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from mock_history import linear_rising, linear_falling, flat

    print("Three quick demos:\n")
    for name, hist in [
        ("RISING  ", linear_rising()),
        ("FALLING ", linear_falling()),
        ("FLAT    ", flat()),
    ]:
        r = best_window(hist, days_ahead=7, model="ml_ridge")
        print(f"{name}  action={r['action']:<11}  today={r['todays_price']:>7.0f}  "
              f"best_day={r['best_day_index']}  "
              f"expected={r['expected_price']:>7.0f}  "
              f"gain={r['gain_vs_today_pct']:>+6.2f}%  "
              f"conf={r['confidence']}")
