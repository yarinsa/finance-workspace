#!/bin/sh
# Fill a throwaway database with this checkout's hand-kept inputs (side files), so the parity
# harness can run with them in tables: scripts/parity/seed_db.sh  (PARITY_DATABASE_URL set).
set -e
[ -n "$PARITY_DATABASE_URL" ] || { echo "set PARITY_DATABASE_URL to a throwaway database" >&2; exit 2; }
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT"
export DATABASE_URL=$PARITY_DATABASE_URL
unset FINANCE_NO_DB
PY=.venv/bin/python
for what in rules schedule freeze settings; do $PY db/input_store.py import $what; done
$PY db/budget_store.py import
$PY db/goal_store.py import
