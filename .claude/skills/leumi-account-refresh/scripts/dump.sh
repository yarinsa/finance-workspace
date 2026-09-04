#!/usr/bin/env bash
#
# Dump raw Bank Leumi (בנק לאומי) account API responses into data/leumi/raw/ —
# accounts, balance summary, and current-account transactions.
#
# The direct-CDP-scrape path (same idea as the discount-* skills, replacing the
# israeli-bank MCP for Leumi). Scrapes Leumi's own gateway at
# hb2.bankleumi.co.il straight from the logged-in browser.
#
# Prereq: a playwright-cli session must already be attached to a logged-in
# Leumi (hb2.bankleumi.co.il) Chrome tab (see SKILL.md). This script does NOT
# log in — login is done by the USER in the visible browser window.
#
# Usage:
#   dump.sh [SESSION] [OUT_DIR] [ACCOUNT_INDEX] [NUM_TX]
#     SESSION        playwright-cli session name        (default: leumi)
#     OUT_DIR        directory for raw json files        (default: <repo>/data/leumi/raw)
#     ACCOUNT_INDEX  Leumi account index (from GetAccounts) (default: 1)
#     NUM_TX         max transactions to pull            (default: 500)
set -euo pipefail

SESSION="${1:-leumi}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
OUT_DIR="${2:-$REPO_ROOT/data/leumi/raw}"
ACCOUNT_INDEX="${3:-1}"
NUM_TX="${4:-500}"

mkdir -p "$OUT_DIR"

HOST="https://hb2.bankleumi.co.il"
BROKER="$HOST/ChannelWCF/Broker.svc/ProcessRequest"

TMP_JS="$(mktemp /tmp/leumi-ep-XXXX.js)"
TMP_RESP="$(mktemp /tmp/leumi-resp-XXXX.json)"
trap 'rm -f "$TMP_JS" "$TMP_RESP"' EXIT

echo "Session  : $SESSION"
echo "Out dir  : $OUT_DIR"
echo "Account  : index $ACCOUNT_INDEX"
echo "Max tx   : $NUM_TX"
echo "----------------------------------------"

# Leumi responses are MORE nested than the others:
#   run-code --raw  -> double-encoded string -> {status, body}
#   body (for Broker calls) -> {"ProcessRequestResult":0,"jsonResp":"<json string>"}
# So we parse the run-code layer twice, then unwrap jsonResp if present and
# write THAT (the real payload) pretty-printed.
#
# STUB GUARD (added — do not remove): a dead SessionID returns HTTP 200 with
# a small error body instead of real data. Before overwriting an existing
# file we require: valid JSON, not login-shell HTML, and no known auth-error
# marker. A legitimately small response ({} or []) is NOT rejected — only
# known failure markers are. On failure: do not write, print an error, leave
# the previous file untouched.
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
    // Broker calls wrap the real data in jsonResp (a JSON string). Unwrap it.
    if (parsed && typeof parsed === "object" && typeof parsed.jsonResp === "string") {
      try { parsed = { ...parsed, jsonResp: JSON.parse(parsed.jsonResp) }; } catch {}
    }
    const flat = JSON.stringify(parsed);
    const AUTH_ERROR_MARKERS = [/actionRequired["\s:]*["\s]*stepup/i, /SME\s*-\s*קלט לא תקין/];
    if (AUTH_ERROR_MARKERS.some(re => re.test(flat))) {
      console.log(`  --  ${String(body.length).padStart(9)}B  ${label}  <-- AUTH-ERROR STUB, NOT WRITTEN (previous file kept)`);
      process.exitCode = 2;
      return;
    }

    const payload = JSON.stringify(parsed, null, 2);
    fs.writeFileSync(outFile, payload);
    const warn = (status !== "200") ? "  <-- non-200" : "";
    console.log(`  ${status}  ${String(body.length).padStart(9)}B  ${label}${warn}`);
})();' "$resp_file" "$out_file" "$label"
}

run_js() { playwright-cli -s="$SESSION" --raw run-code --filename="$TMP_JS" > "$TMP_RESP" 2>/dev/null; }

# Shared snippet: read the live SessionID (32-hex suffix of the SPA's
# "_pouch_sessionDB_<id>" localStorage key). Every Broker call needs it.
SESSION_JS="const k = Object.keys(localStorage).find(k => /_pouch_sessionDB_[0-9a-f]{32}/i.test(k)); const m = k && k.match(/([0-9a-f]{32})/i); const sessionId = m ? m[1] : '';"

# ---- 1. GetAccounts (POST broker) -------------------------------------------
cat > "$TMP_JS" <<EOF
async page => {
  const res = await page.evaluate(async (idx) => {
    $SESSION_JS
    const reqObj = {
      StateName: 'BusinessAccountTrx', ModuleName: 'UC_SO_GetAccounts',
      SessionHeader: { SessionID: sessionId, FIID: 'Leumi' },
      ComboMethod: 'true', RequestedAccountTypes: 'CHECKING',
      ExtAccountPermissions: 'General', AccountSegments: '', AccountIndex: idx,
    };
    const r = await fetch('$BROKER?moduleName=UC_SO_GetAccounts', {
      method: 'POST', credentials: 'include',
      headers: { 'content-type': 'application/json; charset=UTF-8', accept: 'application/json' },
      body: JSON.stringify({ moduleName: 'UC_SO_GetAccounts', reqObj: JSON.stringify(reqObj), version: 'Infra_V2.0' }),
    });
    return { status: r.status, body: await r.text() };
  }, $ACCOUNT_INDEX);
  return JSON.stringify(res);
}
EOF
run_js; parse_and_write "$TMP_RESP" "$OUT_DIR/accounts.json" "accounts.json"

# ---- 2. SummaryData (GET UIApiProxy) ----------------------------------------
cat > "$TMP_JS" <<EOF
async page => {
  const res = await page.evaluate(async (idx) => {
    const r = await fetch('$HOST/UIApiProxy/v1/digital-retails/mobile/accounts/' + idx + '/SummaryData', {
      credentials: 'include', headers: { accept: 'application/json' },
    });
    return { status: r.status, body: await r.text() };
  }, $ACCOUNT_INDEX);
  return JSON.stringify(res);
}
EOF
run_js; parse_and_write "$TMP_RESP" "$OUT_DIR/summary.json" "summary.json"

# ---- 3. Transactions (POST broker, needs live SessionID) --------------------
# The reqObj carries a SessionID that the SPA stores as the 32-hex suffix of a
# localStorage key "_pouch_sessionDB_<id>". We read it live inside the page so
# the request is always authenticated, then pull up to NUM_TX recent rows.
cat > "$TMP_JS" <<EOF
async page => {
  const res = await page.evaluate(async (args) => {
    const { idx, num } = args;
    $SESSION_JS
    const reqObj = {
      StateName: 'BusinessAccountTrx', ModuleName: 'UC_SO_27_GetBusinessAccountTrx',
      SessionHeader: { SessionID: sessionId, FIID: 'Leumi' },
      RequestType: '', FromDateUTC: '', ToDateUTC: '',
      OperationsNumber: String(num), Amount: 0, AmountType1: 0, AmountType2: 0,
      TrxType: '1', ReferenceNumber: '0', BeneficiaryName: '0',
      BeneficiaryBankCode: '0', BeneficiaryBranch: '0', BeneficiaryAccountNumber: '0',
      InvoiceNumber: '0', PeriodType: '0', AccountIndex: idx,
    };
    const r = await fetch('$BROKER?moduleName=UC_SO_27_GetBusinessAccountTrx', {
      method: 'POST', credentials: 'include',
      headers: { 'content-type': 'application/json; charset=UTF-8', accept: 'application/json' },
      body: JSON.stringify({ moduleName: 'UC_SO_27_GetBusinessAccountTrx', reqObj: JSON.stringify(reqObj), version: 'Infra_V2.0' }),
    });
    return { status: r.status, body: await r.text() };
  }, { idx: $ACCOUNT_INDEX, num: $NUM_TX });
  return JSON.stringify(res);
}
EOF
run_js; parse_and_write "$TMP_RESP" "$OUT_DIR/transactions.json" "transactions.json"

echo "----------------------------------------"
echo "Done. Files in $OUT_DIR:"
ls -lh "$OUT_DIR"
