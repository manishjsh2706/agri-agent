"""Add telegram_chat_id column to the farmers table.

Idempotent -- checks if the column already exists before altering.

Run:
    python add_telegram_column.py
"""

from db import init_db


def main() -> None:
    conn = init_db()
    cols = [row["name"] for row in
            conn.execute("PRAGMA table_info(farmers)").fetchall()]
    if "telegram_chat_id" in cols:
        print("Column telegram_chat_id already exists. Nothing to do.")
        return
    conn.execute("ALTER TABLE farmers ADD COLUMN telegram_chat_id INTEGER")
    conn.commit()
    print("Added column telegram_chat_id to farmers table.")


if __name__ == "__main__":
    main()
