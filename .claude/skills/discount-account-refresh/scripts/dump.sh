#!/usr/bin/env bash
#
# Dump raw Bank Discount (בנק דיסקונט) CHECKING-ACCOUNT API responses into
# data/discount/raw/ — balance, transactions, credit cards, deposits.
#
# This is the easier-than-the-MCP path: scrape Discount's own telebank API
# directly from the logged-in browser (same login/site as the mortgage skill).
# For the mortgage loan breakdown use `discount-mortgage-refresh` instead.
#
# Prereq: a playwright-cli session must already be attached to a logged-in
# Discount (start.telebank.co.il) Chrome tab (see SKILL.md). This script does
# NOT log in — login is done by the USER in the visible browser window.
#
# Usage:
#   dump.sh [SESSION] [OUT_DIR] [ACCOUNT] [NUM_TX]
#     SESSION  playwright-cli session name        (default: discount)
#     OUT_DIR  directory to write raw json files   (default: <repo>/data/discount/raw)
#     ACCOUNT  Discount account number             (default: 0123444499)
#     NUM_TX   max transactions to pull            (default: 500)
set -euo pipefail

SESSION="${1:-discount}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
OUT_DIR="${2:-$REPO_ROOT/data/discount/raw}"
ACCOUNT="${3:-0123444499}"
NUM_TX="${4:-500}"

mkdir -p "$OUT_DIR"

BASE="/Titan/gatewayAPI"
# Custom headers the Discount app sends on every gateway call.
HDRS="accept: 'application/json, text/plain, */*', language: 'HEBREW', site: 'retail', accountnumber: '$ACCOUNT', businessprocessid: 'MY_ACCOUNT_HOMEPAGE'"

TMP_JS="$(mktemp /tmp/discount-acc-XXXX.js)"
TMP_RESP="$(mktemp /tmp/discount-resp-XXXX.json)"
trap 'rm -f "$TMP_JS" "$TMP_RESP"' EXIT

echo "Session : $SESSION"
echo "Out dir : $OUT_DIR"
echo "Account : $ACCOUNT"
echo "Max tx  : $NUM_TX"
echo "----------------------------------------"

# run-code --raw output is double-JSON-encoded: parse once -> string, parse
# again -> {status, body}. (Reused verbatim from riseup-raw-refresh.)
#
# STUB GUARD (added — do not remove): a half-authenticated session returns
# HTTP 200 with a few hundred bytes of error JSON (e.g. landing on
# apollo/business2 gives `actionRequired: stepup` or `SME - קלט לא תקין`).
# Before overwriting an existing file we require: valid JSON, not a
# login-shell HTML page, and no known auth-error marker. A legitimately
# small response (e.g. {} or []) is NOT rejected — only markers matching a
# known failure signature are. On failure: do not write, print an error,
# leave the previous file untouched, and mark the run non-zero.
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

# GET helper: fname|path
get_ep() {
  local fname="$1" path="$2"
  cat > "$TMP_JS" <<EOF
async page => {
  const res = await page.evaluate(async () => {
    const r = await fetch('$path', { credentials: 'include', headers: { $HDRS } });
    return { status: r.status, body: await r.text() };
  });
  return JSON.stringify(res);
}
EOF
  playwright-cli -s="$SESSION" --raw run-code --filename="$TMP_JS" > "$TMP_RESP" 2>/dev/null
  parse_and_write "$TMP_RESP" "$OUT_DIR/$fname" "$fname"
}

# POST helper: fname|path|json-body
post_ep() {
  local fname="$1" path="$2" body="$3"
  cat > "$TMP_JS" <<EOF
async page => {
  const res = await page.evaluate(async () => {
    const r = await fetch('$path', {
      method: 'POST', credentials: 'include',
      headers: { $HDRS, 'content-type': 'application/json' },
      body: JSON.stringify($body),
    });
    return { status: r.status, body: await r.text() };
  });
  return JSON.stringify(res);
}
EOF
  playwright-cli -s="$SESSION" --raw run-code --filename="$TMP_JS" > "$TMP_RESP" 2>/dev/null
  parse_and_write "$TMP_RESP" "$OUT_DIR/$fname" "$fname"
}

# ---- Balance & account info --------------------------------------------------
get_ep  "userAccountsData.json"   "$BASE/userAccountsData?FetchAccountsNickName=true&FirstTimeEntry=true"
get_ep  "infoAndBalance.json"     "$BASE/accountDetails/infoAndBalance/$ACCOUNT"
get_ep  "headerData.json"         "$BASE/accountDetails/headerData/$ACCOUNT"
post_ep "dashboardBalances.json"  "$BASE/dashboard/dashboardBalances"  "{AccountNumber:'$ACCOUNT'}"
post_ep "creditLine.json"         "$BASE/account/creditLine"           "{AccountNumber:'$ACCOUNT',SubService:'CurrentAccountLastTransaction'}"

# ---- Transactions (current + past) -------------------------------------------
get_ep  "transactions.json"       "$BASE/lastTransactions/transactions/$ACCOUNT/forHomePage?NumberOfTransactions=$NUM_TX&IsTransactionDetails=True&IsFutureTransactionFlag=True&IsEventNames=True&IsCategoryDescCode=True"
get_ep  "categoriesList.json"     "$BASE/lastTransactions/categoriesList"
get_ep  "totalCreditAndDebitByMonth.json" "$BASE/lastTransactions/totalCreditAndDebitByMonth/$ACCOUNT/3"

# ---- Credit cards ------------------------------------------------------------
get_ep  "creditCards_totalDebitTransactions.json" "$BASE/creditCards/totalDebitTransactions/$ACCOUNT"
get_ep  "creditCards_pastOrFutureDebitTotal.json" "$BASE/creditCards/cardsPastOrFutureDebitTotal/$ACCOUNT/F"
get_ep  "creditCards_cardListForActivation.json"  "$BASE/creditCards/cardListForActivation/$ACCOUNT"

# ---- Deposits ----------------------------------------------------------------
get_ep  "deposits_depositsDetails.json" "$BASE/deposits/depositsDetails/$ACCOUNT/1"

echo "----------------------------------------"
echo "Done. Files in $OUT_DIR:"
ls -lh "$OUT_DIR"
