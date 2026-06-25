#!/usr/bin/env python3
"""
Run once to apply all DB migrations to your Supabase project.
Usage: python migrate.py
"""

import os
from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from agents.tracker_agent import MIGRATION_SQL

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not url or not key:
    raise SystemExit("Set SUPABASE_URL and SUPABASE_KEY in .env first")

db = create_client(url, key)

print("Applying migrations...")
# Supabase Python client doesn't support raw SQL directly; use rpc or REST
# Run each statement that isn't a comment or blank
import re
statements = [s.strip() for s in MIGRATION_SQL.split(";") if s.strip() and not s.strip().startswith("--")]
for stmt in statements:
    try:
        db.rpc("exec_sql", {"query": stmt + ";"}).execute()
        print(f"  OK: {stmt[:60].replace(chr(10),' ')}...")
    except Exception as e:
        # Supabase may not have exec_sql — print for manual run
        print(f"  NOTE: Run manually in SQL editor:\n{stmt};\n")

print("\nDone. If any statements printed 'Run manually', paste them into")
print("your Supabase project → SQL Editor and run them once.")
