#!/usr/bin/env bash
# Refresh Leumi end to end: dry run into a temp dir, show what came back, then (after a yes)
# scrape for real into data/leumi/raw and run the dump validator.
#
#   scrapers/leumi/refresh.sh        # asks before writing data/leumi/raw
#   scrapers/leumi/refresh.sh -y     # no question
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

# Credentials: report missing names only, never values.
missing=()
for k in LEUMI_USERNAME LEUMI_PASSWORD; do
  grep -qE "^$k=.+" .env 2>/dev/null || missing+=("$k")
done
if ((${#missing[@]})); then
  echo "Add to $REPO/.env: ${missing[*]}"
  exit 2
fi

[[ -d scrapers/leumi/node_modules ]] || (cd scrapers/leumi && npm install --silent) || exit 1

DRY="$(mktemp -d /tmp/leumi-dry-XXXX)"
trap 'rm -rf "$DRY"' EXIT

echo "== dry run -> $DRY =="
node scrapers/leumi/scrape.mjs --out "$DRY"
rc=$?
case $rc in
  0) ;;
  3) echo "Leumi refused the login (see LOGIN FAILED above). Fix it in the browser; not retrying."; exit 3 ;;
  *) echo "Dry run failed (exit $rc); data/leumi/raw untouched."; exit $rc ;;
esac

echo "== what came back =="
node -e '
  const fs = require("fs"), dir = process.argv[1];
  const tx = JSON.parse(fs.readFileSync(`${dir}/transactions.json`)).jsonResp.HistoryTransactionsItems || [];
  const s = JSON.parse(fs.readFileSync(`${dir}/summary.json`)), sum = s.jsonResp || s;
  const checking = (sum.TotalPerTypeItems || []).find((t) => t.accountType === "CHECKING");
  const loans = JSON.parse(fs.readFileSync(`${dir}/loans.json`)).loans || [];
  const iso = (d) => d.split("/").reverse().join("-");
  const dates = tx.map((t) => iso(t.DateSO)).sort();
  console.log(`  checking balance : ${checking ? checking.totalPerAccountType : "?"}`);
  console.log(`  transactions     : ${tx.length} (${dates[0] || "-"} .. ${dates.at(-1) || "-"})`);
  for (const l of loans) console.log(`  loan             : ${String(l.loanLabel || "").trim()}  next ${l.balances["סכום התשלום הבא"] || "?"}  ${l.installmentCount} installments`);
' "$DRY" || { echo "Dry-run files are unreadable; data/leumi/raw untouched."; exit 1; }

if [[ "${1:-}" != "-y" ]]; then
  read -r -p "Write this into data/leumi/raw? [y/N] " ok
  [[ "$ok" == [yY]* ]] || { echo "Stopped; data/leumi/raw untouched."; exit 0; }
fi

echo "== real run -> data/leumi/raw =="
node scrapers/leumi/scrape.mjs || exit $?

echo "== validate =="
poetry run python data/validate.py dump leumi
