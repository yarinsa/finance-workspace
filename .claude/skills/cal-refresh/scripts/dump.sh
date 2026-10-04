#!/usr/bin/env bash
#
# Dump raw CAL (כאל / cal-online) credit-card API responses into data/cal/raw/.
#
# CAL's SPA lives at digital-web.cal-online.co.il and talks to api.cal-online.co.il.
# Every authenticated call needs TWO headers:
#   authorization: CALAuthScheme <calConnectToken>   (rotates per login)
#   x-site-id:     09031987-273E-2311-906C-8AF85B17C8D9   (static web-client id)
# The token is NOT a cookie — `credentials:'include'` is not enough. We read the
# live token from sessionStorage["auth-module"].auth.calConnectToken inside the
# page (same idea as Leumi's live SessionID).
#
# Card / account ids are read live too, from sessionStorage["init"].result.cards
# (each card has cardUniqueId, last4Digits, bankAccountUniqueId). The "per-card"
# endpoints iterate THAT fixed, account-owned list — not a blind response walk.
#
# Prereq: a playwright-cli session attached to a logged-in CAL Chrome tab
# (see SKILL.md). This script does NOT log in — the USER logs in in the browser.
#
# Usage:
#   dump.sh [SESSION] [OUT_DIR]
#     SESSION  playwright-cli session name   (default: cal)
#     OUT_DIR  directory for raw json files  (default: <repo>/data/cal/raw)
set -euo pipefail

SESSION="${1:-cal}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
OUT_DIR="${2:-$REPO_ROOT/data/cal/raw}"

mkdir -p "$OUT_DIR"

TMP_JS="$(mktemp /tmp/cal-ep-XXXX.js)"
TMP_RESP="$(mktemp /tmp/cal-resp-XXXX.json)"
trap 'rm -f "$TMP_JS" "$TMP_RESP"' EXIT

echo "Session : $SESSION"
echo "Out dir : $OUT_DIR"
echo "----------------------------------------"

# run-code --raw output is double-JSON-encoded: parse once -> string, parse
# again -> {status, body}. (Same block as the other refresh skills.)
#
# STUB GUARD (added — do not remove): a stale/expired session returns HTTP
# 200 with a small error JSON body instead of real data. Before overwriting
# an existing file we require: valid JSON, not login-shell HTML, and no
# known auth-error marker. A legitimately small response ({} or []) is NOT
# rejected — only known failure markers are. On failure: do not write,
# print an error, leave the previous file untouched.
parse_and_write() {
  local resp_file="$1" out_file="$2" label="$3"
  node -e '(function(){
    const fs = require("fs");
    let raw = fs.readFileSync(process.argv[1], "utf8").trim();
    let obj = JSON.parse(raw);
    if (typeof obj === "string") obj = JSON.parse(obj);   // run-code double-encode
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

run_js() { playwright-cli -s="$SESSION" --raw run-code --filename="$TMP_JS" > "$TMP_RESP" 2>/dev/null; }

# Shared page-side prelude: pull the live token + site-id + cards/account ids
# from sessionStorage, expose a helper `cal(path, body)` that fetches an
# api.cal-online.co.il endpoint with the right headers (GET if body omitted).
PRELUDE=$(cat <<'JS'
const HOST = 'https://api.cal-online.co.il';
const SITE_ID = '09031987-273E-2311-906C-8AF85B17C8D9';
const token = JSON.parse(sessionStorage.getItem('auth-module') || '{}')?.auth?.calConnectToken || '';
const init  = JSON.parse(sessionStorage.getItem('init') || '{}')?.result || {};
const cards = (init.cards || []);
const cardIds = cards.map(c => c.cardUniqueId);
const acct = (cards[0] || {}).bankAccountUniqueId || '';
const cal = async (path, body) => {
  const opts = {
    method: 'POST', credentials: 'include',
    headers: {
      'accept': 'application/json, text/plain, */*',
      'content-type': 'application/json',
      'authorization': 'CALAuthScheme ' + token,
      'x-site-id': SITE_ID,
    },
    body: JSON.stringify(body || {}),
  };
  const r = await fetch(HOST + path, opts);
  return { status: r.status, body: await r.text() };
};
JS
)

# single_ep <fname> <path> <body-js-expr>
#   Runs the prelude then one `cal()` call; body-expr may reference acct/cardIds.
single_ep() {
  local fname="$1" path="$2" bodyexpr="$3"
  cat > "$TMP_JS" <<EOF
async page => {
  const res = await page.evaluate(async () => {
    $PRELUDE
    return await cal('$path', $bodyexpr);
  });
  return JSON.stringify(res);
}
EOF
  run_js
  parse_and_write "$TMP_RESP" "$OUT_DIR/$fname" "$fname"
}

echo "== account / cards =="
# account/init returns the full user + cards list (the canonical cards source).
single_ep "account_init.json" "/Authentication/api/account/init" "{tokenGuid:''}"

echo "== billing summary =="
single_ep "monthlyDebitsSummary.json" "/Transactions/api/financeDashboard/getMonthlyDebitsSummary" "{bankAccountUniqueId: acct}"
single_ep "bigNumberAndDetails.json"  "/Transactions/api/financeDashboard/getBigNumberAndDetails"  "{bankAccountUniqueId: acct}"

echo "== transactions (all cards, last 12 months) =="
# trnType:6 = both billed + future-dated; caller 'dashboard' keeps the wide window.
single_ep "filteredTransactions.json" "/Transactions/api/filteredTransactions/getFilteredTransactions" \
  "(()=>{const now=new Date();const from=new Date(now);from.setFullYear(now.getFullYear()-1);return {bankAccountUniqueID:acct,cards:cardIds.map(id=>({cardUniqueID:id})),fromTransDate:from.toISOString(),toTransDate:now.toISOString(),merchantHebName:'',merchantHebCity:'',trnType:6,fromTrnAmt:0,toTrnAmt:0,transactionsOrigin:0,transCardPresentInd:0,walletTranInd:0,caller:'dashboard'}})()"
single_ep "lastTransactionsDashboard.json" "/Transactions/api/LastTransactionsForDashboard/LastTransactionsForDashboard" "{bankAccountUniqueID: acct, isDesktop: true}"

echo "== pending / not-yet-billed (clearance requests) =="
single_ep "clearanceRequests.json" "/Transactions/api/approvals/getClearanceRequests" "{cardUniqueIDArray: cardIds}"

echo "== per-card transaction details (current billing month) =="
# One file per card; the loop walks the account's OWN fixed card list, writing
# cardTransactions_<last4>_<idx>.json. Not a blind Object.entries walk.
cat > "$TMP_JS" <<'EOF'
async page => {
  const res = await page.evaluate(async () => {
JS_PRELUDE
    const now = new Date();
    const out = [];
    for (const c of cards) {
      const r = await cal('/Transactions/api/transactionsDetails/getCardTransactionsDetails',
        { cardUniqueId: c.cardUniqueId, month: String(now.getMonth() + 1), year: String(now.getFullYear()) });
      out.push({ last4: c.last4Digits, cardUniqueId: c.cardUniqueId, status: r.status, body: r.body });
    }
    return out;
  });
  return JSON.stringify(res);
}
EOF
# splice the live prelude into the per-card script (the heredoc was quoted, so
# JS_PRELUDE is a literal placeholder until now).
PRELUDE="$PRELUDE" perl -0pi -e 's/JS_PRELUDE/$ENV{PRELUDE}/' "$TMP_JS"
run_js
# This response is an ARRAY of {last4, cardUniqueId, status, body}. Split it into
# one pretty file per card.
node -e '
  const fs = require("fs");
  let raw = fs.readFileSync(process.argv[1], "utf8").trim();
  let obj = JSON.parse(raw);
  if (typeof obj === "string") obj = JSON.parse(obj);
  const arr = Array.isArray(obj) ? obj : [];
  arr.forEach((c, i) => {
    let pretty = c.body;
    try { pretty = JSON.stringify(JSON.parse(c.body), null, 2); } catch {}
    const fn = `${process.argv[2]}/cardTransactions_${c.last4 || "x"}_${i}.json`;
    fs.writeFileSync(fn, pretty);
    const warn = String(c.status) !== "200" ? "  <-- non-200" : "";
    console.log(`  ${c.status}  ${String((c.body||"").length).padStart(9)}B  cardTransactions_${c.last4||"x"}_${i}.json${warn}`);
  });
' "$TMP_RESP" "$OUT_DIR"

echo "== loans =="
single_ep "custLoans.json" "/LoanDashboard.API/api/Loans/getCustLoans" \
  "(()=>{const now=new Date();const from=new Date(now);from.setMonth(now.getMonth()-6);const to=new Date(now);to.setMonth(now.getMonth()+2);return {loanType:0,bankUniqueId:acct,startDate:from.toISOString(),endDate:to.toISOString()}})()"

echo "----------------------------------------"
echo "Done. Files in $OUT_DIR:"
ls -lh "$OUT_DIR"
