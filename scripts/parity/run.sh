#!/bin/sh
# Golden parity for the JSON-to-DB migration (docs/json-to-db-migration.md, "Parity harness").
#
#   scripts/parity/run.sh capture DIR   run the chain at a pinned instant, copy the outputs to DIR
#   scripts/parity/run.sh check DIR     run it again and diff against DIR (exit 1 on any difference)
#
# The chain runs with no database (DATABASE_URL unset, digest --no-db) and a fixed hash seed,
# on this checkout's data/ as it is. With PARITY_DATABASE_URL set it runs against that throwaway
# database instead (seed it first: scripts/parity/seed_db.sh), for the inputs that live only
# in tables once their side files are gone. Never point it at the live database. data/digested/ is put back afterwards, so the pinned
# outputs never replace the real ones.
set -e
MODE=$1
DIR=$2
[ -n "$MODE" ] && [ -n "$DIR" ] || { echo "usage: $0 capture|check DIR" >&2; exit 2; }

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
HERE="$ROOT/scripts/parity"
PY="$ROOT/.venv/bin/python"
DIGESTED="$ROOT/data/digested"
cd "$ROOT"
unset DATABASE_URL API_DATABASE_URL FINANCE_DATA_DIR FINANCE_TENANT_ID
export PYTHONHASHSEED=0   # budgets.summary.variable.categories follows set order
if [ -n "$PARITY_DATABASE_URL" ]; then
  export DATABASE_URL=$PARITY_DATABASE_URL
  NODB=""
else
  export FINANCE_NO_DB=1    # data/stores.py readers stay off the database (it would read .env otherwise)
  NODB="--no-db"
fi
[ -f "$ROOT/.env" ] && { echo "run this from a worktree: the main checkout's .env points at the live database" >&2; exit 2; }

SAVED=$(mktemp -d)
cp -R "$DIGESTED"/. "$SAVED"/
trap 'rm -rf "$DIGESTED"; mkdir -p "$DIGESTED"; cp -R "$SAVED"/. "$DIGESTED"/; rm -rf "$SAVED"' EXIT

run() { "$PY" "$HERE/pinned.py" "$@" > /dev/null; }
run data/digest.py --no-normalize $NODB
run data/validate.py
run data/forecast.py
run data/cashflow.py
run data/goals.py

OUT=$DIR
[ "$MODE" = check ] && OUT=$(mktemp -d)
mkdir -p "$OUT"
cp "$DIGESTED"/*.json "$DIGESTED"/*.md "$OUT"/

case $MODE in
  capture) echo "captured $(ls "$OUT" | wc -l | tr -d ' ') files into $OUT" ;;
  check)
    if diff -rq "$DIR" "$OUT"; then echo "parity: all $(ls "$OUT" | wc -l | tr -d ' ') files identical"
    else echo "parity: differences (new outputs in $OUT)" >&2; exit 1; fi ;;
  *) echo "unknown mode $MODE" >&2; exit 2 ;;
esac
