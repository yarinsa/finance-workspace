#!/usr/bin/env bash
#
# Dump raw Bank Discount (בנק דיסקונט) BUSINESS-account API responses into
# data/discount-business/raw/ — balance, transactions, loans, securities, FX,
# savings, guarantees, debit authorizations, checks, credit cards, deposits.
#
# Same login/site as the personal Discount skills, but the BUSINESS app at
# /apollo/business2/ and the business account (0216859524 by default).
# Sibling of discount-account-refresh (personal) — same /Titan/gatewayAPI
# backend, just a different account + extra business products.
#
# Prereq: a playwright-cli session must already be attached to a logged-in
# Discount BUSINESS Chrome tab (see SKILL.md). This script does NOT log in —
# login is done by the USER in the visible browser window.
#
# Usage:
#   dump.sh [SESSION] [OUT_DIR] [ACCOUNT] [NUM_TX]
#     SESSION  playwright-cli session name        (default: discount)
#     OUT_DIR  directory for raw json files        (default: <repo>/data/discount-business/raw)
#     ACCOUNT  Discount business account number    (default: 0216859524)
#     NUM_TX   max transactions to pull            (default: 500)
set -euo pipefail

SESSION="${1:-discount}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
OUT_DIR="${2:-$REPO_ROOT/data/discount-business/raw}"
ACCOUNT="${3:-0216859524}"
NUM_TX="${4:-500}"

mkdir -p "$OUT_DIR"

BASE="/Titan/gatewayAPI"
# The business (SME) app requires site:'sme' — with site:'retail' the gateway
# rejects every call with "SME - קלט לא תקין" (T200108).
HDRS="accept: 'application/json, text/plain, */*', language: 'HEBREW', site: 'sme', accountnumber: '$ACCOUNT', businessprocessid: 'MY_ACCOUNT_HOMEPAGE'"

TMP_JS="$(mktemp /tmp/discount-biz-XXXX.js)"
TMP_RESP="$(mktemp /tmp/discount-resp-XXXX.json)"
trap 'rm -f "$TMP_JS" "$TMP_RESP"' EXIT

# Date helpers for the few endpoints that need a range.
TODAY="$(date +%Y%m%d)"
FAR_FUTURE="$(($(date +%Y)+20))$(date +%m%d)"

echo "Session : $SESSION"
echo "Out dir : $OUT_DIR"
echo "Account : $ACCOUNT (business)"
echo "Max tx  : $NUM_TX"
echo "----------------------------------------"

# run-code --raw output is double-JSON-encoded: parse once -> string, parse
# again -> {status, body}. (Reused verbatim from the other discount skills.)
#
# STUB GUARD (added — do not remove): a stale/rebound session (e.g. this
# business app rebinding the shared login and blocking retail endpoints)
# returns HTTP 200 with a few hundred bytes of error JSON, e.g.
# `SME - קלט לא תקין` or `actionRequired: stepup`. Before overwriting an
# existing file we require: valid JSON, not login-shell HTML, and no known
# auth-error marker. A legitimately small response ({} or []) is NOT
# rejected — only known failure markers are. On failure: do not write,
# print an error, leave the previous file untouched.
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
get_ep  "infoAndBalance.json"     "$BASE/accountDetails/infoAndBalance/$ACCOUNT"
post_ep "dashboardBalances.json"  "$BASE/dashboard/dashboardBalances"  "{AccountNumber:'$ACCOUNT'}"
post_ep "creditLine.json"         "$BASE/account/creditLine"           "{AccountNumber:'$ACCOUNT',SubService:'CurrentAccountLastTransaction'}"
get_ep  "liabilities.json"        "$BASE/balance/liabilities/$ACCOUNT/Explicit"

# ---- Transactions ------------------------------------------------------------
get_ep  "transactions.json"       "$BASE/lastTransactions/transactions/$ACCOUNT/forHomePage?NumberOfTransactions=$NUM_TX&IsTransactionDetails=True&IsFutureTransactionFlag=True&IsEventNames=True&IsCategoryDescCode=True"

# ---- Dashboard product balances (business) -----------------------------------
get_ep  "dashboard_loansBalance.json"           "$BASE/dashboard/loansBalance/$ACCOUNT"
get_ep  "dashboard_savingsBalance.json"         "$BASE/dashboard/savingsBalance/$ACCOUNT"
get_ep  "dashboard_securitiesBalance.json"      "$BASE/dashboard/securitiesBalance/$ACCOUNT"
get_ep  "dashboard_foreignAccountsBalance.json" "$BASE/dashboard/foreignAccountsBalance/$ACCOUNT"

# ---- Loans -------------------------------------------------------------------
get_ep  "onlineLoans_loansQuery.json" "$BASE/onlineLoans/loansQuery/$ACCOUNT"

# ---- Deposits ----------------------------------------------------------------
get_ep  "deposits_depositsDetails.json" "$BASE/deposits/depositsDetails/$ACCOUNT/1"

# ---- Credit cards ------------------------------------------------------------
get_ep  "creditCards_pastOrFutureDebitTotal_F.json" "$BASE/creditCards/cardsPastOrFutureDebitTotal/$ACCOUNT/F"
get_ep  "creditCards_pastOrFutureDebitTotal_P.json" "$BASE/creditCards/cardsPastOrFutureDebitTotal/$ACCOUNT/P"
get_ep  "creditCards_accountFutureDebitsTotal.json" "$BASE/creditCards/accountFutureDebitsTotal/$ACCOUNT"
get_ep  "creditCards_cardFutureCredits.json"        "$BASE/creditCards/cardFutureCredits/$ACCOUNT/True"
get_ep  "creditCards_cardListForActivation.json"    "$BASE/creditCards/cardListForActivation/$ACCOUNT"

# ---- Business-specific -------------------------------------------------------
post_ep "guarantee_guaranteesInfo.json" "$BASE/guarantee/guaranteesInfo" "{AccountNumber:'$ACCOUNT',GuaranteesTypeFilter:0,BuildingNumFilter:'',ApartmentNumFilter:'',BeneficiaryNameFilter:'',GuaranteeIDNumFilter:'',BaseAmountFromFilter:'',BaseAmountToFilter:'',GuaranteeStatusCodeFilter:'',InfoParameters:{BalanceType:4,RequestedMonth:'',RequestedQuarter:'',RequestedYear:'',EstablishmentFromDate:'',EstablishmentToDate:'',ValidityFromDate:'',ValidityToDate:'',ClosingFromDate:'',ClosingToDate:''}}"
get_ep  "debitAuthorizations_list.json" "$BASE/debitAuthorizations/list/$ACCOUNT/NotRequired"
post_ep "checks_draftChecksTotals.json" "$BASE/checks/draftChecksTotals" "{AccountNumber:'$ACCOUNT',FromDate:'$TODAY',ToDate:'$FAR_FUTURE'}"

echo "----------------------------------------"
echo "Done. Files in $OUT_DIR:"
ls -lh "$OUT_DIR"
