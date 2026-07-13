"""Standalone sanity test for list_all_crops_near_me_tool.

Bypasses the LLM entirely -- calls the tool directly and prints what it
returns. If this shows the right crops with distances, the backend is
fine and any issue is in the LLM routing / prompt.

Run:
    python test_all_crops_tool.py
"""

from agent_tools import list_all_crops_near_me_tool

# Manish's coords (Hadapsar-ish, roughly)
result = list_all_crops_near_me_tool.invoke({
    "farmer_lat": 18.4956,
    "farmer_lon": 73.8588,
    "vehicle":    "mini_truck",
    "radius_km":  60,
})

print(f"count      : {result.get('count')}")
print(f"as_of_date : {result.get('as_of_date')}")
print()
print(f"{'crop':<18} {'top_mandi':<24} {'net_price':>10} {'dist':>6}")
print("-" * 65)
for row in result.get("crops", []):
    crop = str(row.get("crop") or "?")
    mandi = str(row.get("top_mandi") or "?")
    net = row.get("net_price")
    dist = row.get("distance_km")
    net_s = f"Rs{net:.2f}" if isinstance(net, (int, float)) else "-"
    dist_s = f"{dist} km" if dist is not None else "-"
    print(f"{crop:<18} {mandi:<24} {net_s:>10} {dist_s:>6}")

print()
if result.get("count", 0) == 0:
    print("NO CROPS RETURNED -- backend is empty. Check DB.")
else:
    print(f"OK -- {result['count']} crops.")
