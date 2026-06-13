#!/usr/bin/env bash
#
# Dump raw cal API responses into data/cal/raw/.
#
# Scaffolded by add-bank-source. FILL IN the endpoint list (see TODO below)
# after discovering the real endpoints from the logged-in browser.
#
# Prereq: a playwright-cli session must already be attached to a logged-in
# cal Chrome tab (see SKILL.md). This script does NOT log in — login is
# done by the USER in the visible browser window.
#
# Usage:
#   dump.sh [SESSION] [OUT_DIR]
#     SESSION  playwright-cli session name        (default: cal)
#     OUT_DIR  directory for raw json files        (default: <repo>/data/cal/raw)
set -euo pipefail

SESSION="${1:-cal}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
OUT_DIR="${2:-$REPO_ROOT/data/cal/raw}"

mkdir -p "$OUT_DIR"

# TODO: set the API host base path and the custom headers the real requests
# carry (copy them from `playwright-cli -s=cal request <N>`). Example for a
# host-relative API:  HOST="https://api.example.com"
HOST=""
# Example headers — replace with what the bank actually requires:
HDRS="accept: 'application/json', 'content-type': 'application/json'"

TMP_JS="$(mktemp /tmp/cal-ep-XXXX.js)"
TMP_RESP="$(mktemp /tmp/cal-resp-XXXX.json)"
trap 'rm -f "$TMP_JS" "$TMP_RESP"' EXIT

echo "Session : $SESSION"
echo "Out dir : $OUT_DIR"
echo "----------------------------------------"

# run-code --raw output is double-JSON-encoded: parse once -> string, parse
# again -> {status, body}. DO NOT CHANGE this block. If your bank wraps the real
# payload in an inner JSON string (like Leumi's `jsonResp`), unwrap it where
# marked.
parse_and_write() {
  local resp_file="$1" out_file="$2" label="$3"
  node -e '
    const fs = require("fs");
    let raw = fs.readFileSync(process.argv[1], "utf8").trim();
    let obj = JSON.parse(raw);
    if (typeof obj === "string") obj = JSON.parse(obj);   // run-code double-encode
    let body = obj.body ?? "";
    let pretty = body;
    try {
      let parsed = JSON.parse(body);
      // --- OPTIONAL third-level unwrap (delete if not needed) ---------------
      // if (parsed && typeof parsed.jsonResp === "string") {
      //   try { parsed = { ...parsed, jsonResp: JSON.parse(parsed.jsonResp) }; } catch {}
      // }
      pretty = JSON.stringify(parsed, null, 2);
    } catch {}
    fs.writeFileSync(process.argv[2], pretty);
    const status = String(obj.status);
    const warn = (status !== "200") ? "  <-- non-200" : "";
    console.log(`  ${status}  ${String(body.length).padStart(9)}B  ${process.argv[3]}${warn}`);
  ' "$resp_file" "$out_file" "$label"
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

# ============================================================================
# TODO: replace these examples with your confirmed endpoints (fixed + named).
# NEVER loop over a response with Object.entries — list endpoints explicitly.
# ============================================================================
# get_ep  "balance.json"       "$HOST/api/balance"
# get_ep  "transactions.json"  "$HOST/api/transactions?count=500"
# post_ep "summary.json"       "$HOST/api/summary"  "{AccountNumber:'XXXX'}"
echo "  !! No endpoints configured yet — edit the TODO list in dump.sh."

echo "----------------------------------------"
echo "Done. Files in $OUT_DIR:"
ls -lh "$OUT_DIR"
