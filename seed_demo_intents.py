"""One-shot: add two intents so daily_advice.py has something to fire on.

Safe to re-run -- it only ADDS rows (never deletes). If you want to clean
up later, either mark them fulfilled/cancelled via open_intents.py or
delete manually.

Run:
    python seed_demo_intents.py
"""

from datetime import date, timedelta

from db import init_db
from open_intents import create_intent


TARGET_PHONE = "9876500001"   # the farmer you've been testing with


def main() -> None:
    conn = init_db()

    # Deadline in 2 days -> should fire DEADLINE_WARNING (medium urgency)
    d1 = (date.today() + timedelta(days=2)).isoformat()
    id1 = create_intent(
        conn,
        phone=TARGET_PHONE,
        crop="Onion",
        quantity_q=20,
        deadline=d1,
        notes="demo intent -- near deadline",
    )
    print(f"created intent {id1}: Onion 20q, deadline {d1}")

    # Deadline TOMORROW -> should fire DEADLINE_WARNING (high urgency)
    d2 = (date.today() + timedelta(days=1)).isoformat()
    id2 = create_intent(
        conn,
        phone=TARGET_PHONE,
        crop="Tomato",
        quantity_q=5,
        deadline=d2,
        notes="demo intent -- deadline tomorrow",
    )
    print(f"created intent {id2}: Tomato 5q, deadline {d2}")

    print()
    print("Now run:  python daily_advice.py")


if __name__ == "__main__":
    main()
