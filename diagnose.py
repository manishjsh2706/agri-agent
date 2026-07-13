# --- Step 1: check the CODE ---
with open('db.py') as f:
    code = f.read()
print("Step 1 — is 'open_intents' text in db.py?")
if 'open_intents' in code:
    print("  YES")
else:
    print("  NO --> db.py did not get the update. Re-paste db.py.")
    raise SystemExit()

# --- Step 2: force init_db() and check the DB ---
print()
print("Step 2 — force init_db() and list tables")
from db import init_db
conn = init_db()
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("  Tables:", tables)
if 'open_intents' in tables:
    print("  SUCCESS — open_intents table exists.")
else:
    print("  Something else is wrong. Paste the output back to me.")