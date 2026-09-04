#!/usr/bin/env bash
#
# Dump raw harel API responses into data/harel/raw/.
#
# Scaffolded by add-bank-source. FILL IN the endpoint list (see TODO below)
# after discovering the real endpoints from the logged-in browser.
#
# Prereq: a playwright-cli session must already be attached to a logged-in
# harel Chrome tab (see SKILL.md). This script does NOT log in — login is
# done by the USER in the visible browser window.
#
# Usage:
#   dump.sh [SESSION] [OUT_DIR]
#     SESSION  playwright-cli session name        (default: harel)
#     OUT_DIR  directory for raw json files        (default: <repo>/data/harel/raw)
set -euo pipefail

SESSION="${1:-harel}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
OUT_DIR="${2:-$REPO_ROOT/data/harel/raw}"

mkdir -p "$OUT_DIR"

# The client-view micro-frontend API. Auth is cookie session PLUS a per-page-load
# `ticket` query param — cookies alone return 404, and the ticket ROTATES on every
# page load, so it must be read live (see get_ticket below). Never hardcode it.
HOST="https://digital.harel-group.co.il/apps.client-view/client-view"
PORTAL="https://www.harel-group.co.il"
CLIENT_VIEW_PAGE="$PORTAL/personal-info/my-harel/Pages/client-view.aspx"
HDRS="accept: 'application/json'"

TMP_JS="$(mktemp /tmp/harel-ep-XXXX.js)"
TMP_RESP="$(mktemp /tmp/harel-resp-XXXX.json)"
trap 'rm -f "$TMP_JS" "$TMP_RESP"' EXIT

echo "Session : $SESSION"
echo "Out dir : $OUT_DIR"
echo "----------------------------------------"

# run-code --raw output is double-JSON-encoded: parse once -> string, parse
# again -> {status, body}. DO NOT CHANGE this block. If your bank wraps the real
# payload in an inner JSON string (like Leumi's `jsonResp`), unwrap it where
# marked.
#
# STUB GUARD (added — do not remove): a stale ticket / expired session
# returns HTTP 200 with a small error JSON body instead of real data.
# Before overwriting an existing file we require: valid JSON, not
# login-shell HTML, and no known auth-error marker. A legitimately small
# response ({} or []) is NOT rejected — only known failure markers are. On
# failure: do not write, print an error, leave the previous file untouched.
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
    // --- OPTIONAL third-level unwrap (delete if not needed) ---------------
    // if (parsed && typeof parsed.jsonResp === "string") {
    //   try { parsed = { ...parsed, jsonResp: JSON.parse(parsed.jsonResp) }; } catch {}
    // }
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

# GET helper:  get_ep <fname> <path-or-url>
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

# POST helper:  post_ep <fname> <path-or-url> <js-object-literal-body>
post_ep() {
  local fname="$1" path="$2" body="$3"
  cat > "$TMP_JS" <<EOF
async page => {
  const res = await page.evaluate(async () => {
    const r = await fetch('$path', {
      method: 'POST', credentials: 'include',
      headers: { $HDRS },
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

# ---------------------------------------------------------------------------
# Mint + extract the live ticket.
#
# The ticket is not in cookies, localStorage, sessionStorage or the DOM — it is
# generated per page load and only ever appears in the client-view page's own
# XHR URLs. So: load that page, let it fire its requests, then recover the ticket
# from the performance resource timeline. It rotates every load, hence "live".
# ---------------------------------------------------------------------------
get_ticket() {
  playwright-cli -s="$SESSION" goto "$CLIENT_VIEW_PAGE" >/dev/null 2>&1
  local ticket=""
  for _ in $(seq 1 15); do
    sleep 2
    ticket="$(playwright-cli -s="$SESSION" --raw eval \
      '(()=>{const e=performance.getEntriesByType("resource").map(r=>r.name).find(n=>n.includes("ticket="));const m=e&&e.match(/ticket=([0-9a-f]{40})/i);return m?m[1]:""})()' \
      2>/dev/null | tail -1 | tr -d '"' )"
    [ -n "$ticket" ] && [ "$ticket" != "null" ] && break
  done
  printf '%s' "$ticket"
}

echo "Minting live ticket…"
TICKET="$(get_ticket)"
if [ -z "$TICKET" ]; then
  echo "  !! Could not obtain a ticket — the session is probably logged out."
  echo "     Log in at $CLIENT_VIEW_PAGE in the Chrome on port 9227, then re-run."
  exit 1
fi
echo "  ticket: ${TICKET:0:8}… (rotates per run)"
CT="$(date +%s)000"
Q="ctime=$CT&ticket=$TICKET"
echo "----------------------------------------"

# --- verified endpoints (fixed + named; never iterate a response) ------------
# Savings balances by topicId: {"70": pension, "62": study funds} — the headline
# accumulated figures (₪, thousands-separated strings).
get_ep "online-data.json"        "$HOST/online-data?$Q"
# Product/topic index: which savings products exist, policy counts, lobby urls,
# plus generalDetails (incl. birthDate, used by projection.py).
get_ep "customer-products.json"  "$HOST/customer-products?$Q"
# Supporting context — claims and open requests against the policies.
get_ep "client-claims-by-area.json" "$HOST/client-claims-by-area?$Q"
get_ep "client-requests.json"       "$HOST/client-requests?$Q"

echo "----------------------------------------"
echo "Done. Files in $OUT_DIR:"
ls -lh "$OUT_DIR"
