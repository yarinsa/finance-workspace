#!/usr/bin/env bash
#
# Dump raw amex API responses into data/amex/raw/.
#
# STRATEGY (changed 2026-08-09 — read this before "fixing" it back):
# We do NOT reconstruct API requests via page.evaluate()/fetch() any more. The
# real auth cookies (`authentication_shared`, `JSESSIONID`) are HttpOnly, so
# they are invisible to document.cookie and are NOT carried by a fetch() run
# inside page.evaluate(), no matter how carefully credentials are set. Two
# patterns DO work, and this script uses both:
#   1. Navigate the SPA and CAPTURE the responses it makes itself (bootstrap
#      endpoints — cardList, transactionsList, initContent, etc).
#   2. Reissue a POST via page.request.post() with the browser context's own
#      cookie jar. CORRECTION (2026-09-04): an earlier version of this comment
#      claimed page.request.post() "also returned login HTML" and was
#      abandoned. That claim was WRONG — page.request.post() DOES carry the
#      HttpOnly cookies from the context jar (unlike page.evaluate/fetch,
#      which runs in page-JS-land and never sees HttpOnly cookies at all).
#      Re-verified 2026-09-04 issuing GetTransactionsList per-card POSTs; see
#      step 2 below. Use it for any endpoint the bootstrap capture doesn't
#      cover, rather than declaring it broken again.
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
OUT_DIR="${2:-$REPO_ROOT/data/amex/raw}"

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

# ---------------------------------------------------------------------------
# Step 3: per-card transactions_<suffix>_<month>.json — the files
# data/amex/normalize.py actually globs (transactions_*.json). The bootstrap
# capture above (GetTransactionsList) is the OWN account's aggregate view,
# not the per-card monthly pull normalize.py expects; without this step
# normalize.py silently keeps reading whatever per-card files were last
# written by hand, and a refresh reports green while the ledger goes stale.
#
# Request shape recovered from the page's own POST body (DevTools -> Network
# while paging per-card history in the UI): same GetTransactionsList
# endpoint, with an explicit card4Number / billingMonth / companyCode /
# isPartner body instead of the no-args aggregate call the bootstrap makes.
#
# Auth: page.request.post() — NOT page.evaluate()+fetch(). The context
# request API carries the browser context's cookie jar, including the
# HttpOnly authentication_shared/JSESSIONID cookies that page.evaluate/fetch
# can never see. (See the corrected note at the top of this file — this was
# previously miscategorized as "also fails".)
#
# Only ACTIVE cards are pulled (cardList.json's isActive flag); inactive/
# closed cards are left untouched, matching normalize.py's own card roster.
# Pulls the current AND previous billing month per card.
# ---------------------------------------------------------------------------
CARD_LIST_FILE="$OUT_DIR/cardList.json"
if [ ! -s "$CARD_LIST_FILE" ]; then
  echo
  echo "WARNING: cardList.json missing/empty — skipping per-card transaction pulls."
  echo "(cardList capture must have failed above; per-card files left untouched.)"
else
  # Compute the ACTIVE-card list outside the run-code snippet (that snippet's
  # async (page) => {...} body has no require()/process.env — see SKILL.md's
  # run-code rules) and splice it into the JS as a literal, same as $HDRS
  # elsewhere in this file.
  ACTIVE_CARDS_JSON="$(node -e '
    const fs = require("fs");
    const cl = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
    const cards = (cl?.data?.cardsList || [])
      .filter(c => c.isActive)
      .map(c => ({ cardSuffix: c.cardSuffix, companyCode: c.companyCode }));
    process.stdout.write(JSON.stringify(cards));
  ' "$CARD_LIST_FILE")"

  if [ "$ACTIVE_CARDS_JSON" = "[]" ] || [ -z "$ACTIVE_CARDS_JSON" ]; then
    echo
    echo "WARNING: no active cards found in cardList.json — skipping per-card pulls."
  else
    echo "== fetching per-card transactions (active cards, current + previous month) =="
    cat > "$TMP_JS" <<EOF
async (page) => {
  const cards = $ACTIVE_CARDS_JSON;

  const now = new Date();
  const months = [0, 1].map(back => {
    const d = new Date(now.getFullYear(), now.getMonth() - back, 1);
    return \`\${d.getFullYear()}\${String(d.getMonth() + 1).padStart(2, '0')}\`;
  });

  const out = [];
  for (const c of cards) {
    for (const billingMonth of months) {
      try {
        const res = await page.request.post(
          'https://web.americanexpress.co.il/ocp/transactions/DigitalV3.Transactions/GetTransactionsList',
          {
            data: {
              card4Number: c.cardSuffix,
              billingMonth,
              companyCode: c.companyCode,
              isPartner: c.companyCode !== 77,
            },
          }
        );
        out.push({ suffix: c.cardSuffix, month: billingMonth, status: res.status(), body: await res.text() });
      } catch (e) {
        out.push({ suffix: c.cardSuffix, month: billingMonth, status: 0, body: String(e) });
      }
    }
  }
  return JSON.stringify(out);
}
EOF
    playwright-cli -s="$SESSION" --raw run-code --filename="$TMP_JS" > "$TMP_RESP" 2>/dev/null

  node -e '
    const fs = require("fs"), path = require("path");
    const outDir = process.argv[2];

    let raw = fs.readFileSync(process.argv[1], "utf8").trim();
    let arr = JSON.parse(raw);
    if (typeof arr === "string") arr = JSON.parse(arr);   // run-code double-encode
    if (!Array.isArray(arr)) arr = [];

    let wrote = 0, skipped = 0;
    for (const item of arr) {
      const fname = `transactions_${item.suffix}_${item.month}.json`;
      const body = item.body ?? "";
      if (String(item.status) !== "200") {
        console.log(`  --  status ${item.status}  ${String(body.length).padStart(9)}B  ${fname}  <-- non-200, NOT WRITTEN`);
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
    if (skipped) console.log(`\n(${skipped} per-card pull(s) skipped; existing files, if any, left untouched.)`);
    if (wrote === 0) {
      console.error("\nWARNING: no per-card transaction files written this run.");
      process.exitCode = 1;
    }
  ' "$TMP_RESP" "$OUT_DIR"
  fi
fi

echo "----------------------------------------"
echo "Done. Files in $OUT_DIR:"
ls -lh "$OUT_DIR"
