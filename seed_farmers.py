"""Seed a few sample farmers and stock entries so the chat has real
profiles to test with.

Run once with:

    python seed_farmers.py

Then start the chat (`python chat_app.py`) and type a sample phone number
into the "Your phone:" field at the top, click Identify, and chat.

Re-running this script is safe: it upserts farmers by phone.
"""

from db import init_db
from farmer_profile import save_farmer, set_stock, list_stock


# ----------------------------------------------------------------------
# Sample farmers (phone -> profile)
# ----------------------------------------------------------------------
SAMPLE_FARMERS = [
    {
        "phone":     "9876500001",
        "name":      "Praveen Joshi",
        "village":   "Hadapsar",
        "latitude":  18.5089,
        "longitude": 73.9259,
        "vehicle":   "mini_truck",
        "crops":     "Onion,Wheat,Tomato",
        "language":  "Hi",
    },
    {
        "phone":     "9876500002",
        "name":      "Naveen Joshi",
        "village":   "Baramati",
        "latitude":  18.1514,
        "longitude": 74.5800,
        "vehicle":   "tractor_trolley",
        "crops":     "Onion,Soyabean",
        "language":  "mr",
    },
    {
        "phone":     "9074674426",
        "name":      "Manish Joshi",
        "village":   "Chinchwad",
        "latitude":  18.6420,
        "longitude": 73.7860,
        "vehicle":   "truck",
        "crops":     "Wheat,Arhar (Tur/Red Gram)(Whole)",
        "language":  "en",
    },
]

# Stock per farmer (phone -> [(crop, quantity_q, harvested_on, notes), ...])
SAMPLE_STOCK = {
    "9876500001": [
        ("Onion", 20, "18/06/2026", "Local variety"),
        ("Wheat", 12, "10/06/2026", "Stored at home"),
    ],
    "9876500002": [
        ("Onion", 35, "20/07/2026", "First harvest of season"),
    ],
    "9074674426": [
        ("Wheat", 18, "16/07/2026", ""),
        ("Onion", 25, "18/07/2026", "Local variety"),
        ("Tomato", 50, "20/06/2026", "Stored at home"),
    ],
}


def main():
    conn = init_db()

    for f in SAMPLE_FARMERS:
        save_farmer(
            conn,
            phone=f["phone"], name=f["name"],
            latitude=f["latitude"], longitude=f["longitude"],
            vehicle=f["vehicle"], village=f["village"],
            crops=f["crops"], language=f["language"],
        )
        print(f"  upserted farmer {f['name']:<15} (phone {f['phone']})")

    # Only add stock if the farmer has none yet (so re-runs don't pile up).
    for phone, entries in SAMPLE_STOCK.items():
        existing = list_stock(conn, phone)
        if existing:
            print(f"  stock already present for {phone} -- skipping ({len(existing)} rows)")
            continue
        for crop, qty, hd, notes in entries:
            sid = set_stock(conn, phone, crop, qty,
                            harvested_on=hd, notes=notes)
            print(f"  added stock id {sid}: {phone}  {crop:<10}  {qty} q")

    print()
    print("Done. Try these phone numbers in the chat:")
    for f in SAMPLE_FARMERS:
        print(f"  {f['phone']}  ({f['name']}, {f['village']})")


if __name__ == "__main__":
    main()
