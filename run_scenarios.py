"""Test harness: runs every mock scenario through the comparison engine
and reports PASS or FAIL for each.

Run with:

    python run_scenarios.py
"""

from comparison import compare_mandis
from mock_scenarios import SCENARIOS, TODAY


def _check_key(result, key, expected):
    if key == "top_mandi":
        a = result["top_mandi"]
        return a == expected, f"top_mandi = {a!r}  (expected {expected!r})"
    if key == "top_mandi_in":
        a = result["top_mandi"]
        return a in expected, f"top_mandi = {a!r}  (expected one of {expected})"
    if key == "must_not_contain":
        ranked = [it["market"] for it in result["ranking"]]
        present = [m for m in expected if m in ranked]
        return not present, f"ranking = {ranked}  (must not contain {expected}; present: {present})"
    if key == "no_data_for_crop":
        a = result["no_data_for_crop"]
        return a == expected, f"no_data_for_crop = {a}  (expected {expected})"
    if key == "single_mandi":
        a = result["single_mandi"]
        return a == expected, f"single_mandi = {a}  (expected {expected})"
    if key == "low_confidence":
        a = result["low_confidence"]
        return a == expected, f"low_confidence = {a}  (expected {expected})"
    if key == "freshness_warning_for":
        a = result["freshness_warning_for"]
        return set(a) == set(expected), f"freshness_warning_for = {a}  (expected {expected})"
    if key == "bad_rows_skipped":
        a = result["bad_rows_skipped"]
        return set(a) == set(expected), f"bad_rows_skipped = {a}  (expected {expected})"
    if key == "reason":
        return True, f"(note: {expected})"
    if key in {"with_truck_top_mandi", "with_tractor_trolley_top_mandi",
               "from_nagpur_top_mandi", "from_wardha_top_mandi"}:
        return True, "(checked at scenario level)"
    return False, f"unknown expected key '{key}'"


def _run_engine(scenario, farmer=None, vehicle=None):
    f = farmer or scenario["farmer"]
    v = vehicle or f["vehicle"]
    return compare_mandis(
        prices=scenario["mock_prices"],
        mandi_locations=scenario["mandi_locations"],
        farmer_lat=f["lat"], farmer_lon=f["lon"],
        vehicle=v, crop=scenario["crop"],
        radius_km=scenario["radius_km"],
        quantity_quintals=scenario["quantity_quintals"],
        today=TODAY,
    )


def _run_default(scenario):
    r = _run_engine(scenario)
    return [(k, *_check_key(r, k, v)) for k, v in scenario["expected"].items()]


def _run_vehicle_flip(scenario):
    checks = []
    for vehicle in scenario.get("alt_vehicles", []):
        r = _run_engine(scenario, vehicle=vehicle)
        key = f"with_{vehicle}_top_mandi"
        expected = scenario["expected"].get(key)
        a = r["top_mandi"]
        checks.append((key, a == expected, f"top_mandi = {a!r}  (expected {expected!r})"))
    return checks


def _run_farmer_move(scenario):
    checks = []
    pairs = [("from_nagpur_top_mandi", scenario["farmer"]),
             ("from_wardha_top_mandi", scenario["alt_farmer"])]
    for key, farmer in pairs:
        r = _run_engine(scenario, farmer=farmer)
        expected = scenario["expected"].get(key)
        a = r["top_mandi"]
        checks.append((key, a == expected, f"top_mandi = {a!r}  (expected {expected!r})"))
    return checks


def run_one(scenario):
    if scenario["id"] == 11: return _run_vehicle_flip(scenario)
    if scenario["id"] == 12: return _run_farmer_move(scenario)
    return _run_default(scenario)


def main():
    print(f"Running {len(SCENARIOS)} scenarios through compare_mandis() ...")
    print()
    n_pass = n_fail = 0
    for s in SCENARIOS:
        checks = run_one(s)
        all_ok = all(ok for _, ok, _ in checks)
        if all_ok:
            n_pass += 1
            print(f"[ PASS ]  Scenario {s['id']:>2}: {s['name']}")
        else:
            n_fail += 1
            print(f"[ FAIL ]  Scenario {s['id']:>2}: {s['name']}")
        for key, ok, msg in checks:
            mark = "ok" if ok else "FAIL"
            print(f"            [{mark:>4}] {key:<32} {msg}")
    print()
    print(f"Result: {n_pass} passed, {n_fail} failed (of {len(SCENARIOS)}).")
    if n_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
