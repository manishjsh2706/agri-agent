"""Set a farmer's preferred language in the DB.

Language codes accepted:
    en  -> English
    hi  -> Hindi
    mr  -> Marathi

Usage:
    python set_language.py 9876500001 hi
    python set_language.py 9876500002 mr
    python set_language.py 9074674426 en

Run with no arguments to see the current language for every farmer.
"""

import sys
from db import init_db

VALID = {"en", "hi", "mr"}


def show_all(conn):
    print("Current language settings:")
    for r in conn.execute(
        "SELECT phone, name, language FROM farmers ORDER BY name"
    ):
        print(f"  {r['phone']}  {r['name']:<18}  {r['language']}")


def main():
    conn = init_db()

    if len(sys.argv) == 1:
        show_all(conn)
        print()
        print("To change: python set_language.py <phone> <lang>")
        print("  lang must be one of: en | hi | mr")
        return

    if len(sys.argv) != 3:
        print("usage: python set_language.py <phone> <lang>")
        sys.exit(1)

    phone, lang = sys.argv[1], sys.argv[2].lower()
    if lang not in VALID:
        print(f"lang must be one of: {sorted(VALID)}")
        sys.exit(1)

    n = conn.execute(
        "UPDATE farmers SET language = ?, updated_at = datetime('now') "
        "WHERE phone = ?",
        (lang, phone),
    ).rowcount
    conn.commit()

    if n == 0:
        print(f"No farmer found with phone {phone}.")
        sys.exit(1)
    print(f"OK: set {phone} language = {lang}")
    print()
    show_all(conn)


if __name__ == "__main__":
    main()
