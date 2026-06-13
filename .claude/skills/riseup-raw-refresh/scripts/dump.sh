#!/usr/bin/env bash
#
# Dump raw RiseUp API responses into data/riseup/raw/.
#
# Prereq: a playwright-cli session must already be attached to a logged-in
# RiseUp Chrome tab (see SKILL.md for how to set that up). This script does
# NOT log in — login is done by the user in the visible browser window.
#
# Usage:
#   dump.sh [SESSION] [OUT_DIR]
#     SESSION  playwright-cli session name        (default: riseup)
#     OUT_DIR  directory to write raw json files  (default: <repo>/data/riseup/raw)
#
set -euo pipefail

SESSION="${1:-riseup}"
# Repo root = three levels up from this script (.claude/skills/riseup-raw-refresh/scripts)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
OUT_DIR="${2:-$REPO_ROOT/data/riseup/raw}"

mkdir -p "$OUT_DIR"

# Current month endpoint is date-dependent: /api/budget/YYYY-MM/<startDay>
MONTH="$(date +%Y-%m)"
# RiseUp's cashflow month index (the trailing segment); 6 has worked, but we
# read the real start day below and fall back to 6.
BUDGET_MONTH_EP="budget/${MONTH}/6"

# Endpoints to capture. Add more here as we discover them.
EPS=(
  "$BUDGET_MONTH_EP"
  "budget/current"
  "budget/oldest"
  "current-balance"
  "current-credit-card-debt"
  "cashflow-start-day"
  "insights/all"
  "application-state"
  "credentials-info"
  "creds-to-accounts"
  "subscription-state-simplified"
  "consolidated/customer-state"
  "cashflow-models/churn/data"
  "plans"
)

TMP_JS="$(mktemp /tmp/riseup-ep-XXXX.js)"
TMP_RESP="$(mktemp /tmp/riseup-resp-XXXX.json)"
trap 'rm -f "$TMP_JS" "$TMP_RESP"' EXIT

echo "Session : $SESSION"
echo "Out dir : $OUT_DIR"
echo "Month   : $MONTH"
echo "----------------------------------------"

for ep in "${EPS[@]}"; do
  fname="$(echo "$ep" | tr '/' '_').json"

  cat > "$TMP_JS" <<EOF
async page => {
  const res = await page.evaluate(async () => {
    const r = await fetch('/api/$ep', { credentials: 'include', headers: { accept: 'application/json' } });
    return { status: r.status, body: await r.text() };
  });
  return JSON.stringify(res);
}
EOF

  playwright-cli -s="$SESSION" --raw run-code --filename="$TMP_JS" > "$TMP_RESP" 2>/dev/null

  # run-code with --raw returns the JSON.stringify'd value, which is itself
  # double-encoded: parse once -> string, parse again -> {status, body}.
  node -e '
    const fs = require("fs");
    let raw = fs.readFileSync(process.argv[1], "utf8").trim();
    let obj = JSON.parse(raw);
    if (typeof obj === "string") obj = JSON.parse(obj);
    let body = obj.body ?? "";
    let pretty = body;
    try { pretty = JSON.stringify(JSON.parse(body), null, 2); } catch {}
    fs.writeFileSync(process.argv[2], pretty);
    const status = String(obj.status);
    const warn = (status !== "200") ? "  <-- non-200" : "";
    console.log(`  ${status}  ${String(body.length).padStart(9)}B  ${process.argv[3]}${warn}`);
  ' "$TMP_RESP" "$OUT_DIR/$fname" "$fname"
done

echo "----------------------------------------"
echo "Done. Files in $OUT_DIR:"
ls -lh "$OUT_DIR"
