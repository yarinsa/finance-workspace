#!/usr/bin/env bash
#
# Dump raw Bank Discount (בנק דיסקונט) mortgage + loan API responses into
# data/discount-mortgage/raw/.
#
# Prereq: a playwright-cli session must already be attached to a logged-in
# Discount (start.telebank.co.il) Chrome tab (see SKILL.md). This script does
# NOT log in — login is done by the USER in the visible browser window.
#
# Usage:
#   dump.sh [SESSION] [OUT_DIR] [ACCOUNT]
#     SESSION  playwright-cli session name        (default: discount)
#     OUT_DIR  directory to write raw json files   (default: <repo>/data/discount-mortgage/raw)
#     ACCOUNT  Discount account number             (default: 0123444499)
#
# The mortgage data lives behind three calls on start.telebank.co.il:
#   1. GET  /Titan/gatewayAPI/mortgage/accountsList/<ACCOUNT>  -> account ids
#   2. POST /Titan/gatewayAPI/mortgage/details  with a body derived from (1)
#         -> per-track breakdown (principal, rates, schedule dates, fees)
#   3. GET  /Titan/gatewayAPI/onlineLoans/loansQuery/<ACCOUNT> -> non-mortgage loans
#
# The page already holds the auth cookies + session, so every fetch uses
# credentials:'include' and copies the custom headers the app sends.
set -euo pipefail

SESSION="${1:-discount}"
# Repo root = four levels up (.claude/skills/discount-mortgage-refresh/scripts)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
OUT_DIR="${2:-$REPO_ROOT/data/discount-mortgage/raw}"
ACCOUNT="${3:-0123444499}"

mkdir -p "$OUT_DIR"

BASE="/Titan/gatewayAPI"
# Custom headers the Discount app sends on every gateway call. accountnumber
# and businessprocessid are required; the rest are harmless to include.
HDRS="accept: 'application/json, text/plain, */*', language: 'HEBREW', site: 'retail', accountnumber: '$ACCOUNT', businessprocessid: 'MY_ACCOUNT_HOMEPAGE'"

TMP_JS="$(mktemp /tmp/discount-ep-XXXX.js)"
TMP_RESP="$(mktemp /tmp/discount-resp-XXXX.json)"
trap 'rm -f "$TMP_JS" "$TMP_RESP"' EXIT

echo "Session : $SESSION"
echo "Out dir : $OUT_DIR"
echo "Account : $ACCOUNT"
echo "----------------------------------------"

# run-code with --raw returns the JSON.stringify'd value, which is itself
# double-encoded: parse once -> string, parse again -> {status, body}.
# (Reused verbatim from riseup-raw-refresh — do NOT change the double-parse.)
#
# STUB GUARD (added — do not remove): mortgage_details.json is the classic
# case — real ~10-17KB, but landing on the wrong Discount app (business2
# rebound the session) returns HTTP 200 with ~350B of `actionRequired:
# stepup`. Before overwriting an existing file we require: valid JSON, not
# login-shell HTML, and no known auth-error marker. A legitimately small
# response ({} or []) is NOT rejected — only known failure markers are. On
# failure: do not write, print an error, leave the previous file untouched.
parse_and_write() {
  local resp_file="$1" out_file="$2" label="$3"
  node -e '(function(){
    const fs = require("fs");
    let raw = fs.readFileSync(process.argv[1], "utf8").trim();
    let obj = JSON.parse(raw);
    if (typeof obj === "string") obj = JSON.parse(obj);
    let body = obj.body ?? "";
    const status = String(obj.status);
    const outFile = process.argv[2], label = process.argv[3];

    if (/^\s*<(!doctype|html)/i.test(body)) {
      console.log(`  --  ${String(body.length).padStart(9)}B  ${label}  <-- LOGIN-SHELL HTML, NOT WRITTEN (previous file kept)`);
      process.exitCode = 2;
      return;
    }
    let parsed;
    try { parsed = JSON.parse(body); }
    catch {
      console.log(`  --  ${String(body.length).padStart(9)}B  ${label}  <-- NOT JSON, NOT WRITTEN (previous file kept)`);
      process.exitCode = 2;
      return;
    }
    const flat = JSON.stringify(parsed);
    const AUTH_ERROR_MARKERS = [/actionRequired["\s:]*["\s]*stepup/i, /SME\s*-\s*קלט לא תקין/];
    if (AUTH_ERROR_MARKERS.some(re => re.test(flat))) {
      console.log(`  --  ${String(body.length).padStart(9)}B  ${label}  <-- AUTH-ERROR STUB, NOT WRITTEN (previous file kept)`);
      process.exitCode = 2;
      return;
    }

    const pretty = JSON.stringify(parsed, null, 2);
    fs.writeFileSync(outFile, pretty);
    const warn = (status !== "200") ? "  <-- non-200" : "";
    console.log(`  ${status}  ${String(body.length).padStart(9)}B  ${label}${warn}`);
})();' "$resp_file" "$out_file" "$label"
}

# ---- 1. GET endpoints (fixed, named — never Object.entries a response) -------
# fname|path
GET_EPS=(
  "accountsList.json|$BASE/mortgage/accountsList/$ACCOUNT"
  "onlineLoans_loansQuery.json|$BASE/onlineLoans/loansQuery/$ACCOUNT"
)

for entry in "${GET_EPS[@]}"; do
  fname="${entry%%|*}"
  path="${entry#*|}"

  cat > "$TMP_JS" <<EOF
async page => {
  const res = await page.evaluate(async () => {
    const r = await fetch('$path', {
      credentials: 'include',
      headers: { $HDRS },
    });
    return { status: r.status, body: await r.text() };
  });
  return JSON.stringify(res);
}
EOF

  playwright-cli -s="$SESSION" --raw run-code --filename="$TMP_JS" > "$TMP_RESP" 2>/dev/null
  parse_and_write "$TMP_RESP" "$OUT_DIR/$fname" "$fname"
done

# ---- 2. POST mortgage/details ------------------------------------------------
# Body is built from accountsList: each AccountEntry.OldAccountInfo becomes a
# MortgageAccountEntry. We do this inside the page so it always matches the
# live account ids (no hardcoding).
cat > "$TMP_JS" <<EOF
async page => {
  const res = await page.evaluate(async () => {
    const headers = { $HDRS, 'content-type': 'application/json' };
    // Re-fetch accountsList to derive the POST body (cheap, keeps ids fresh).
    const al = await fetch('$BASE/mortgage/accountsList/$ACCOUNT', {
      credentials: 'include', headers,
    });
    const alJson = await al.json();
    let entries = alJson?.MortgageAccountsList?.AccountList?.AccountEntry ?? [];
    if (!Array.isArray(entries)) entries = [entries];
    const mortgageEntries = entries.map(e => {
      const o = e.OldAccountInfo || {};
      return {
        BankID: o.BankID, BranchID: o.BranchID, AccountType: o.AccountType,
        CurrencyID: o.CurrencyID, AccountID: o.AccountID,
      };
    });
    const body = { MortgageAccountBlock: { MortgageAccountEntry: mortgageEntries } };
    const r = await fetch('$BASE/mortgage/details', {
      method: 'POST', credentials: 'include', headers,
      body: JSON.stringify(body),
    });
    return { status: r.status, body: await r.text() };
  });
  return JSON.stringify(res);
}
EOF

playwright-cli -s="$SESSION" --raw run-code --filename="$TMP_JS" > "$TMP_RESP" 2>/dev/null
parse_and_write "$TMP_RESP" "$OUT_DIR/mortgage_details.json" "mortgage_details.json"

echo "----------------------------------------"
echo "Done. Files in $OUT_DIR:"
ls -lh "$OUT_DIR"
