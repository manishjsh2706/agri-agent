"""Stage C evaluation harness: how good is each forecast model?

Why this file matters
---------------------
Any ML project lives or dies on its evaluation. This module implements
the standard methodology:

  1. WALK-FORWARD CROSS-VALIDATION
     We never let the model see future data while training. We slide a
     training window forward day-by-day, ask the model to predict the
     next `horizon` days, compare against ground truth, and repeat.

  2. ERROR METRICS (three of them, because each has a weakness)
        MAE   -- average absolute error in rupees
        RMSE  -- penalises large errors more (squared)
        MAPE  -- percentage error, easier to compare across crops

  3. LEADERBOARD
     For each mock history, we run every model through walk-forward CV
     and rank them. The lowest-error model wins.

Run with:

    python forecast_eval.py

You'll see a leaderboard table per scenario.
"""

from __future__ import annotations

import math

from forecast import MODELS, forecast_with
from mock_history import ALL_HISTORIES


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def mae(actual, predicted) -> float:
    return sum(abs(a - p) for a, p in zip(actual, predicted)) / len(actual)


def rmse(actual, predicted) -> float:
    return math.sqrt(sum((a - p) ** 2 for a, p in zip(actual, predicted))
                     / len(actual))


def mape(actual, predicted) -> float:
    """Mean absolute percentage error. Skips rows where actual == 0."""
    pairs = [(a, p) for a, p in zip(actual, predicted) if a != 0]
    if not pairs:
        return float("nan")
    return 100 * sum(abs(a - p) / abs(a) for a, p in pairs) / len(pairs)


# ---------------------------------------------------------------------------
# Walk-forward cross-validation
# ---------------------------------------------------------------------------
def walk_forward_cv(
    history,
    model_name: str,
    horizon: int = 7,
    min_train: int = 21,
    step: int = 1,
) -> dict:
    """Slide a forecasting window through `history` and average the errors.

    For each train-size N >= min_train:
      - train (i.e. fit + predict) on history[:N]
      - true future values are history[N : N+horizon]
      - record errors
    Move N forward by `step` and repeat until we run out of room.

    Returns dict { folds, mae, rmse, mape }.
    """
    n = len(history)
    if n < min_train + horizon:
        return {"folds": 0, "mae": float("nan"),
                "rmse": float("nan"), "mape": float("nan")}

    all_actual: list[float] = []
    all_predicted: list[float] = []
    folds = 0

    for split in range(min_train, n - horizon + 1, step):
        train = history[:split]
        truth = [p for _, p in history[split:split + horizon]]
        preds = forecast_with(model_name, train, horizon)
        all_actual.extend(truth)
        all_predicted.extend(preds)
        folds += 1

    return {
        "folds": folds,
        "mae":   round(mae(all_actual, all_predicted), 2),
        "rmse":  round(rmse(all_actual, all_predicted), 2),
        "mape":  round(mape(all_actual, all_predicted), 2),
    }


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------
def leaderboard(history, horizon: int = 7) -> list[dict]:
    """Run every model in MODELS against `history` and return a ranked list."""
    rows = []
    for name in MODELS:
        m = walk_forward_cv(history, name, horizon=horizon)
        rows.append({"model": name, **m})
    rows.sort(key=lambda r: (r["mape"] if r["mape"] == r["mape"] else 1e9))
    return rows


def _print_leaderboard(scenario_name: str, rows: list[dict]) -> None:
    print(f"\nScenario: {scenario_name}")
    print(f"  {'rank':<5}{'model':<20}{'folds':>6}{'MAE':>10}"
          f"{'RMSE':>10}{'MAPE %':>10}")
    print("  " + "-" * 60)
    for i, r in enumerate(rows, start=1):
        mape_str = "  n/a " if r["mape"] != r["mape"] else f"{r['mape']:>9.2f}"
        print(f"  {i:<5}{r['model']:<20}{r['folds']:>6}"
              f"{r['mae']:>10.2f}{r['rmse']:>10.2f}{mape_str}")


def main():
    print("Forecast model leaderboard")
    print("==========================")
    print("Lower MAPE / MAE / RMSE is better. Best model per scenario at the top.")
    for name, h in ALL_HISTORIES.items():
        rows = leaderboard(h, horizon=7)
        _print_leaderboard(name, rows)


if __name__ == "__main__":
    main()
