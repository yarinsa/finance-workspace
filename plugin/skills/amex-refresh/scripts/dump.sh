#!/usr/bin/env bash
#
# Dump raw amex API responses into data/amex/raw/.
#
# STRATEGY (changed 2026-08-09 — read this before "fixing" it back):
# We do NOT reconstruct API requests any more. We navigate the SPA and CAPTURE
# the responses it makes itself. Reason: the real auth cookies
# (`authentication_shared`, `JSESSIONID`) are HttpOnly, so they are invisible to
# document.cookie and are NOT carried by a fetch() inside page.evaluate. Even
# page.request.post() with the context cookie jar came back as login-shell HTML.
# Letting the app issue its own calls is the only pattern verified to work.
#
# Prereq: a playwright-cli session must already be attached to a logged-in
# amex Chrome tab (see SKILL.md). This script does NOT log in — login is
# done by the USER in the visible browser window.
#
# Usage:
#   dump.sh [SESSION] [OUT_DIR]
#     SESSION  playwright-cli session name        (default: amex)
#     OUT_DIR  directory for raw json files        (default: <repo>/data/amex/raw)
set -euo pipefail

SESSION="${1:-amex}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
FINANCE_DATA_DIR="${FINANCE_DATA_DIR:-$REPO_ROOT/data}"
OUT_DIR="${2:-$FINANCE_DATA_DIR/amex/raw}"

mkdir -p "$OUT_DIR"

TMP_JS="$(mktemp /tmp/amex-ep-XXXX.js)"
TMP_RESP="$(mktemp /tmp/amex-resp-XXXX.json)"
trap 'rm -f "$TMP_JS" "$TMP_RESP"' EXIT

echo "Session : $SESSION"
echo "Out dir : $OUT_DIR"
echo "----------------------------------------"

# ---------------------------------------------------------------------------
# Step 0: liveness gate. Distinguishes "logged out" from "endpoint moved" BEFORE
# we conclude anything. Never report "needs login" without this passing/failing.
# ---------------------------------------------------------------------------
if ! "$SCRIPT_DIR/check_session.sh" "$SESSION"; then
  echo
  echo "ABORT: session not live. Nothing written — existing dump preserved."
  exit 1
fi

# ---------------------------------------------------------------------------
# Step 1: navigate the SPA and capture its own POST responses.
#
# The live app calls .../ocp/transactions/DigitalV3.Transactions/<Method>.
# (The old .../ocp/statuspage/DigitalV3.StatusPage/... paths are STALE — they
# return 200 + ~3.6KB of login-shell HTML regardless of session state.)
#
# Navigating to /transactions triggers, all with real JSON bodies:
#   InitContent · GetCampaign · GetCardList · GetTransactionsList · GetPersonalComponents
#
# Snippet rules for `run-code --filename=` (this build):
#   - BARE async function expression. No module.exports, no top-level statements.
#   - require() is NOT available.
#   - console.log does not reliably surface — RETURN a string/JSON.
# ---------------------------------------------------------------------------
cat > "$TMP_JS" <<'EOF'
async (page) => {
  const captured = {};
  page.on('response', async (r) => {
    const m = r.url().match(/DigitalV3\.Transactions\/(\w+)$/);
    if (m && r.request().method() === 'POST') {
      try { captured[m[1]] = await r.text(); } catch (e) {}
    }
  });

  await page.goto('https://web.americanexpress.co.il/transactions',
                  { waitUntil: 'networkidle', timeout: 45000 }).catch(() => {});
  await page.waitForTimeout(9000);

  return JSON.stringify(captured);
}
EOF

echo "== navigating /transactions and capturing SPA responses =="
playwright-cli -s="$SESSION" --raw run-code --filename="$TMP_JS" > "$TMP_RESP" 2>/dev/null

# ---------------------------------------------------------------------------
# Step 2: write each captured method to its own file — but ONLY if it is real
# JSON. Login-shell HTML or a tiny error stub must NEVER overwrite a good dump.
# This guard is load-bearing: it protected the Aug 1 dump through three failed
# runs. Do not soften it.
# ---------------------------------------------------------------------------
node -e '
  const fs = require("fs"), path = require("path");
  const outDir = process.argv[2];

  let raw = fs.readFileSync(process.argv[1], "utf8").trim();
  let obj = JSON.parse(raw);
  if (typeof obj === "string") obj = JSON.parse(obj);   // run-code double-encode

  // method name -> output filename
  const FILES = {
    GetCardList:           "cardList.json",
    GetTransactionsList:   "transactionsList.json",
    InitContent:           "initContent.json",
    GetPersonalComponents: "personalComponents.json",
    GetCampaign:           "campaign.json",
  };

  let wrote = 0, skipped = 0;
  for (const [method, fname] of Object.entries(FILES)) {
    const body = obj[method];
    if (body == null) {
      console.log(`  --      not captured  ${fname}  <-- SKIPPED (kept previous)`);
      skipped++;
      continue;
    }
    if (/^\s*<(!doctype|html)/i.test(body)) {
      console.log(`  --  ${String(body.length).padStart(9)}B  ${fname}  <-- LOGIN-SHELL HTML, NOT WRITTEN`);
      skipped++;
      continue;
    }
    let pretty;
    try { pretty = JSON.stringify(JSON.parse(body), null, 2); }
    catch {
      console.log(`  --  ${String(body.length).padStart(9)}B  ${fname}  <-- NOT JSON, NOT WRITTEN`);
      skipped++;
      continue;
    }
    fs.writeFileSync(path.join(outDir, fname), pretty);
    console.log(`  ok  ${String(body.length).padStart(9)}B  ${fname}`);
    wrote++;
  }

  if (wrote === 0) {
    console.error("\nERROR: nothing valid captured. Existing dump left untouched.");
    console.error("Session was verified LIVE before this ran, so the likely cause is");
    console.error("that the SPA route or the DigitalV3.Transactions method names moved");
    console.error("again. Re-discover them in DevTools -> Network. DO NOT tell the user");
    console.error("to log in again.");
    process.exit(2);
  }
  if (skipped) console.log(`\n(${skipped} endpoint(s) skipped; their previous files are intact.)`);
' "$TMP_RESP" "$OUT_DIR"

echo "----------------------------------------"
echo "Done. Files in $OUT_DIR:"
ls -lh "$OUT_DIR"
