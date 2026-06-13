#!/usr/bin/env bash
#
# Dump raw amex API responses into data/amex/raw/.
#
# Scaffolded by add-bank-source. FILL IN the endpoint list (see TODO below)
# after discovering the real endpoints from the logged-in browser.
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

# AMEX Israel (operated by Isracard/ICC). The SPA lives at web.americanexpress.co.il
# and talks to its own /ocp/<area>/DigitalV3.<Area>/<Method> endpoints. Auth is
# COOKIE-ONLY — no bearer/CSRF header, so credentials:'include' is all we need.
# (companyCode 77 = AMEX, 11 = Isracard partner cards; cardSuffix = last 4.)
HOST="https://web.americanexpress.co.il"
HDRS="accept: 'application/json', 'content-type': 'application/json'"

TMP_JS="$(mktemp /tmp/amex-ep-XXXX.js)"
TMP_RESP="$(mktemp /tmp/amex-resp-XXXX.json)"
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
# Endpoints (fixed + named). The card list drives every per-card call below;
# we read it once from GetCardList, never blind-walk a response.
# ============================================================================
SP="$HOST/ocp/statuspage/DigitalV3.StatusPage"   # dashboard / status page module
TX="$HOST/ocp/transactions/DigitalV3.Transactions" # full transactions module

echo "== cards + balance summary =="
# cardsList[] (companyCode, cardSuffix, cardName, status, ...) + billing totals
# (billingSumSekel, next/last billing dates). The canonical source of cards.
post_ep "cardList.json"        "$SP/GetCardList" "{companyCode:'99',cardSuffixLength:4}"

echo "== direct debits (standing orders) =="
get_ep  "directDebitList.json" "$SP/GetDirectDebitList"

# Pull the active card list (companyCode + last4) from the response we just
# wrote, so the per-card / multi-card bodies below use the account's OWN cards.
CARDS_JSON=$(node -e '
  const fs=require("fs");
  let d={};
  try { d=JSON.parse(fs.readFileSync(process.argv[1],"utf8")).data||{}; } catch {}
  const cards=(d.cardsList||[])
    .filter(c=>c && c.cardSuffix)
    .map(c=>({last4digits:String(c.cardSuffix),companyCode:Number(c.companyCode),isPartner:!!c.isPartner}));
  process.stdout.write(JSON.stringify(cards));
' "$OUT_DIR/cardList.json")
echo "  cards: $CARDS_JSON"

echo "== billing overview + latest transactions (all cards) =="
post_ep "billingsOverview.json"   "$SP/GetBillingsForMonthsOverview" "{monthRange:6,cards:$CARDS_JSON}"
post_ep "latestTransactions.json" "$SP/GetLatestTransactions" \
  "{cards:[$(node -e 'const c=JSON.parse(process.argv[1]);process.stdout.write(c.map(x=>JSON.stringify({last4digits:x.last4digits,companyCode:x.companyCode})).join(","))' "$CARDS_JSON")]}"

echo "== full transactions per card (current + next billing month) =="
# GetTransactionsList is per card AND per billingMonth. Walk the account's fixed
# card list × {current, next} billing month → transactions_<last4>_<mm-yyyy>.json.
# Not a blind response walk — the loop is over OUR cards, written one file each.
cat > "$TMP_JS" <<EOF
async page => {
  const cards = $CARDS_JSON;
  const res = await page.evaluate(async (cards) => {
    const TX = '$TX/GetTransactionsList';
    const mk = (d) => ('0'+(d.getMonth()+1)).slice(-2)+'/'+d.getFullYear();
    const now = new Date();
    const next = new Date(now.getFullYear(), now.getMonth()+1, 1);
    const months = [mk(now), mk(next)];
    const out = [];
    for (const c of cards) {
      for (const bm of months) {
        const r = await fetch(TX, {
          method:'POST', credentials:'include',
          headers:{ $HDRS },
          body: JSON.stringify({ card4Number:c.last4digits, isNextBillingDate:bm===months[1],
            cardStatus:0, billingMonth:'01/'+bm, companyCode:c.companyCode, isPartner:c.isPartner }),
        });
        out.push({ last4:c.last4digits, billingMonth:bm, status:r.status, body: await r.text() });
      }
    }
    return out;
  }, cards);
  return JSON.stringify(res);
}
EOF
playwright-cli -s="$SESSION" --raw run-code --filename="$TMP_JS" > "$TMP_RESP" 2>/dev/null
node -e '
  const fs=require("fs");
  let raw=fs.readFileSync(process.argv[1],"utf8").trim();
  let obj=JSON.parse(raw); if(typeof obj==="string") obj=JSON.parse(obj);
  const arr=Array.isArray(obj)?obj:[];
  for(const t of arr){
    let pretty=t.body; try{pretty=JSON.stringify(JSON.parse(t.body),null,2);}catch{}
    const tag=`${t.last4||"x"}_${(t.billingMonth||"").replace("/","-")}`;
    const fn=`${process.argv[2]}/transactions_${tag}.json`;
    fs.writeFileSync(fn,pretty);
    const warn=String(t.status)!=="200"?"  <-- non-200":"";
    console.log(`  ${t.status}  ${String((t.body||"").length).padStart(9)}B  transactions_${tag}.json${warn}`);
  }
' "$TMP_RESP" "$OUT_DIR"

echo "----------------------------------------"
echo "Done. Files in $OUT_DIR:"
ls -lh "$OUT_DIR"
