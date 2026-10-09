#!/usr/bin/env bash
#
# Dump raw More Investment House (מור בית השקעות) data into data/more/raw/.
#
# The personal-area SPA (my-account.more.co.il/personalarea) fetches balances
# ONCE at login via POST /paapi/accounts/getDashboardAccountsData (Bearer
# AUTH-TOKEN from sessionStorage) and caches the result in
# sessionStorage.accountData. A page reload does NOT refire it. So we read the
# SPA's own cached copy over raw CDP (no request is made, nothing is mutated).
#
# Raw CDP (Node 22 global WebSocket) instead of playwright-cli: attaching
# playwright to a shared multi-tab Chrome has hung, and connectOverCDP did not
# enumerate the more.co.il tab. Only the tab whose URL starts with
# https://my-account.more.co.il/ is touched.
#
# Usage: dump.sh [PORT] [OUT_DIR]     PORT default 9228 (registry port)
set -euo pipefail

PORT="${1:-9228}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
OUT_DIR="${2:-$REPO_ROOT/data/more/raw}"
mkdir -p "$OUT_DIR"

node - "$PORT" "$OUT_DIR" <<'JS'
const fs = require("fs");
const [port, outDir] = process.argv.slice(2);
(async () => {
  const tabs = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const tab = tabs.find(t => t.type === "page" && t.url.startsWith("https://my-account.more.co.il/personalarea"));
  if (!tab) { console.error("No logged-in more.co.il personalarea tab on port " + port); process.exit(2); }
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  const ev = expr => new Promise(res => {
    ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id === 1) res(m.result.result.value); };
    ws.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: { expression: expr, returnByValue: true } }));
  });
  await new Promise(r => ws.onopen = r);
  const raw = await ev(`JSON.stringify({href: location.href, accountData: sessionStorage.getItem("accountData"), tokenExp: sessionStorage.getItem("AUTH-TOKEN-EXP")})`);
  ws.close();
  const o = JSON.parse(raw);
  let data;
  try { data = JSON.parse(o.accountData); } catch { data = null; }
  // Stub guard: never overwrite a good dump with an empty/garbage one.
  if (!Array.isArray(data) || !data[0] || !Array.isArray(data[0].accountData)) {
    console.error(`accountData missing/invalid at ${o.href} — session likely dead (log in again). Previous file kept.`);
    process.exit(2);
  }
  fs.writeFileSync(`${outDir}/dashboard-accounts.json`, JSON.stringify(data, null, 2));
  console.log(`  ok  dashboard-accounts.json  total=${data[0].totalAmount} lastUpdate=${data[0].lastUpdate} (token exp ${o.tokenExp})`);
  process.exit(0);
})().catch(e => { console.error(e.message); process.exit(1); });
JS
ls -lh "$OUT_DIR"
