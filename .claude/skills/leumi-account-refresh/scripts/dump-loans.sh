#!/usr/bin/env bash
#
# Dump raw Bank Leumi (בנק לאומי) LOAN data into data/leumi/raw/ —
# the full amortization schedule (לוח סילוקין / installments) plus per-loan
# general info, balances, interest, and dates.
#
# Companion to dump.sh (which covers the checking account). Leumi's loan pages
# are legacy ASP.NET WebForms (DisplayLoanActivity.aspx / AmortizationSchedule.aspx),
# NOT the Broker/UIApiProxy JSON gateway — so this script fetches the rendered
# HTML through the logged-in browser and extracts the tables via in-page
# DOMParser. The amortization grid (table id="Table") is rendered on page load,
# one loan per ?index=N.
#
# Discovering the loans: DisplayLoanActivity.aspx's #ddlLoans <select> lists each
# loan with its account index. Defaults below (3,4) are this customer's two
# unindexed fixed-rate term loans (מט"י ז"א לא צמוד). If the loan set changes,
# re-read the dropdown options and update LOAN_INDICES.
#
# Prereq: a playwright-cli session already attached to a logged-in Leumi tab
# (see SKILL.md). This script does NOT log in.
#
# Usage:
#   dump-loans.sh [SESSION] [OUT_DIR] [LOAN_INDICES]
#     SESSION       playwright-cli session name   (default: leumi)
#     OUT_DIR       raw json/html output dir       (default: <repo>/data/leumi/raw)
#     LOAN_INDICES  space-separated indices         (default: "3 4")
set -euo pipefail

SESSION="${1:-leumi}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
OUT_DIR="${2:-$REPO_ROOT/data/leumi/raw}"
LOAN_INDICES="${3:-3 4}"

mkdir -p "$OUT_DIR"
HOST="https://hb2.bankleumi.co.il"

TMP_JS="$(mktemp /tmp/leumi-loan-XXXX.js)"
TMP_RESP="$(mktemp /tmp/leumi-loan-XXXX.json)"
trap 'rm -f "$TMP_JS" "$TMP_RESP"' EXIT

echo "Session : $SESSION"
echo "Out dir : $OUT_DIR"
echo "Loans   : $LOAN_INDICES"
echo "----------------------------------------"

run_js() { playwright-cli -s="$SESSION" --raw run-code --filename="$TMP_JS" > "$TMP_RESP" 2>/dev/null; }

# ---- 1. Per-loan amortization schedule + general info ------------------------
# For each index: goto AmortizationSchedule.aspx?index=N (renders grid table
# id="Table"), then fetch DisplayLoanActivity.aspx?index=N for the key/value
# sections. Returns one JSON object per index; we merge them all into loans.json.
INDICES_JSON="[$(echo "$LOAN_INDICES" | tr ' ' ',')]"
cat > "$TMP_JS" <<EOF
async page => {
  const indices = $INDICES_JSON;
  const clean = s => (s||'').replace(/ /g,' ').replace(/\s+/g,' ').trim();
  const num = s => { if(s==null) return null; const n=parseFloat(String(s).replace(/,/g,'').replace(/[^\d.\-]/g,'')); return isNaN(n)?null:n; };
  const kv = rows => Object.fromEntries(rows.map(r => [String(r[0]||'').replace(/:\$/,'').trim(), r[1]]));
  const loans = [];
  for (const idx of indices) {
    // Amortization grid: page renders table#Table on load.
    await page.goto('$HOST/eBanking/LoanAndMortgages/AmortizationSchedule.aspx?index=' + idx, { waitUntil: 'networkidle' }).catch(()=>{});
    await page.waitForTimeout(2500);
    const amort = await page.evaluate(() => {
      const cl = s => (s||'').replace(/ /g,' ').replace(/\s+/g,' ').trim();
      const t = document.getElementById('Table');
      const sel = document.getElementById('ddlLoans');
      const rows = t ? [...t.querySelectorAll('tr')].map(tr => [...tr.querySelectorAll('th,td')].map(c => cl(c.textContent))).filter(r => r.some(c => c)) : [];
      return { loan: sel && sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].text.trim() : null, rows };
    });
    // Per-loan key/value sections from the activity page.
    const sections = await page.evaluate(async (idx) => {
      const cl = s => (s||'').replace(/ /g,' ').replace(/\s+/g,' ').trim();
      const r = await fetch('$HOST/eBanking/LoanAndMortgages/DisplayLoanActivity.aspx?index=' + idx, { credentials: 'include' });
      const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
      const out = {};
      [...doc.querySelectorAll('table')].forEach(t => {
        const rows = [...t.querySelectorAll('tr')].map(tr => [...tr.querySelectorAll('th,td')].map(c => cl(c.textContent))).filter(r => r.some(c => c));
        if (rows.length >= 2 && rows.length <= 10) {
          const title = rows[0][0];
          if (/^(מידע כללי|יתרות|ריביות|תאריכים)\$/.test(title)) out[title] = rows.slice(1).filter(r => r.length >= 2).map(r => [r[0], r[1]]);
        }
      });
      return out;
    }, idx);

    const [hdr, ...body] = amort.rows.length ? amort.rows : [[]];
    const installments = body.map(r => ({
      paymentDate: r[0], principal: num(r[1]), interest: num(r[2]), balanceAfter: num(r[3]), totalPayment: num(r[4]),
    })).filter(x => x.paymentDate && /\d{2}\/\d{2}\/\d{2}/.test(x.paymentDate));

    loans.push({
      index: idx, loanLabel: amort.loan, header: hdr,
      generalInfo: kv(sections['מידע כללי'] || []),
      balances: kv(sections['יתרות'] || []),
      interest: kv(sections['ריביות'] || []),
      dates: kv(sections['תאריכים'] || []),
      installmentCount: installments.length, installments,
    });
  }
  return JSON.stringify({ source: 'hb2.bankleumi.co.il - LoanAndMortgages', capturedAt: new Date().toISOString(), loans });
}
EOF
run_js
node -e '
  const fs = require("fs");
  let obj = JSON.parse(fs.readFileSync(process.argv[1], "utf8").trim());
  if (typeof obj === "string") obj = JSON.parse(obj);   // run-code double-encode
  fs.writeFileSync(process.argv[2], JSON.stringify(obj, null, 2));
  for (const l of obj.loans) console.log(`  loan ${String(l.loanLabel||"").trim()}  index=${l.index}  ${l.installmentCount} installments`);
' "$TMP_RESP" "$OUT_DIR/loans.json"

# ---- 2. Raw HTML snapshots (summary + per-loan activity) ---------------------
HTML_INDICES="$(echo "$LOAN_INDICES" | sed 's/ /,/g')"
cat > "$TMP_JS" <<EOF
async page => {
  const res = await page.evaluate(async (indices) => {
    const out = {};
    out['loan-summary'] = await (await fetch('$HOST/eBanking/LoanAndMortgages/DisplayLoansAndMortgagesSummary.aspx?from=sideMenu', { credentials: 'include' })).text();
    for (const idx of indices) out['loan-activity-' + idx] = await (await fetch('$HOST/eBanking/LoanAndMortgages/DisplayLoanActivity.aspx?index=' + idx, { credentials: 'include' })).text();
    return out;
  }, [$HTML_INDICES]);
  return JSON.stringify(res);
}
EOF
run_js
node -e '
  const fs = require("fs");
  let obj = JSON.parse(fs.readFileSync(process.argv[1], "utf8").trim());
  if (typeof obj === "string") obj = JSON.parse(obj);
  const dir = process.argv[2];
  for (const [k, html] of Object.entries(obj)) { fs.writeFileSync(`${dir}/${k}.html`, html); console.log(`  ${k}.html  ${html.length}B`); }
' "$TMP_RESP" "$OUT_DIR"

echo "----------------------------------------"
echo "Done. Loan files in $OUT_DIR:"
ls -lh "$OUT_DIR"/loan*.html "$OUT_DIR"/loans.json
