#!/usr/bin/env bash
#
# Dump raw Analyst (אנליסט / amitim.analyst.co.il) savings data into data/analyst/raw/.
#
# The customer portal's balances come from ONE call the SPA makes at login:
#   POST /AnalystCustomersApiFront/api/Accounts/GetCustomerSumFinancialData  (body {})
# Auth is cookie-only (HttpOnly, sent automatically by an in-tab fetch) — no
# bearer header; sessionStorage.auth is an empty object. GET returns 405.
# The response body is a JSON *string* of JSON (double-encoded), unwrapped below.
#
# Raw CDP (Node 22 global WebSocket) instead of playwright-cli: attaching
# playwright to these multi-tab Chromes has hung (see refresh/more). Only the
# tab whose URL starts with https://amitim.analyst.co.il/ is touched, and it is
# never navigated.
#
# Usage: dump.sh [PORT] [OUT_DIR]     PORT default 9229 (registry port)
set -euo pipefail

PORT="${1:-9229}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
OUT_DIR="${2:-$REPO_ROOT/data/analyst/raw}"
mkdir -p "$OUT_DIR"

node - "$PORT" "$OUT_DIR" <<'JS'
const fs = require("fs");
const [port, outDir] = process.argv.slice(2);
const API = "/AnalystCustomersApiFront/api/Accounts/GetCustomerSumFinancialData";
(async () => {
  const tabs = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const tab = tabs.find(t => t.type === "page" && t.url.startsWith("https://amitim.analyst.co.il/"));
  if (!tab) { console.error("No amitim.analyst.co.il tab on port " + port + " — open/log in and re-run."); process.exit(2); }
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  const expr = `(async () => {
    const r = await fetch(${JSON.stringify(API)}, { method: "POST", credentials: "include",
      headers: { accept: "application/json", "content-type": "application/json" }, body: "{}" });
    return JSON.stringify({ status: r.status, href: location.href, body: await r.text() });
  })()`;
  const raw = await new Promise(res => {
    ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id === 1) res(m.result.result.value); };
    ws.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: { expression: expr, returnByValue: true, awaitPromise: true } }));
  });
  ws.close();
  const o = JSON.parse(raw);
  let data = null;
  try { data = JSON.parse(o.body); while (typeof data === "string") data = JSON.parse(data); } catch {}
  // Stub guard: an expired session answers 200 with an error/HTML body. Never
  // overwrite a good dump with it — keep the previous file and say so.
  const products = data?.data?.sumFinancialData?.products;
  if (o.status !== 200 || !data || data.isError || !Array.isArray(products)) {
    console.error(`Bad response (HTTP ${o.status}, ${String(o.body).length}B) at ${o.href} — session likely lapsed or endpoint moved. Previous file kept.`);
    process.exit(2);
  }
  fs.writeFileSync(`${outDir}/sum-financial-data.json`, JSON.stringify(data, null, 2));
  const dates = [...new Set(products.map(p => p.revaluationDate))].join(",");
  console.log(`  ok  sum-financial-data.json  total=${data.data.customerTotalBalance} products=${products.length} asOf=${dates}`);
  process.exit(0);
})().catch(e => { console.error(e.message); process.exit(1); });
JS
ls -lh "$OUT_DIR"
