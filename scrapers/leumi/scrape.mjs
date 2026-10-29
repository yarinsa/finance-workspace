#!/usr/bin/env node
// Deterministic Bank Leumi scrape: logs in by itself, headless, with LEUMI_USERNAME /
// LEUMI_PASSWORD from <repo>/.env (same flow as israeli-bank-scrapers' Leumi scraper), then makes
// the same calls as .claude/skills/leumi-account-refresh/scripts/dump.sh (accounts, summary,
// transactions) and dump-loans.sh (loan schedule + HTML snapshots), writing the same raw files to
// data/leumi/raw. No Chrome/CDP session needed.
//
// Exit codes: 0 ok · 1 failure (retryable) · 2 missing env / bad args ·
// 3 LOGIN FAILED (wrong password, password renewal, blocked, OTP demanded): needs a human, do not retry.
import puppeteer from 'puppeteer';
import dotenv from 'dotenv';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadEnv, dataDir } from '../tenant.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '../..');
loadEnv(repo, dotenv);

const HOST = 'https://hb2.bankleumi.co.il';
const BROKER = `${HOST}/ChannelWCF/Broker.svc/ProcessRequest`;
const INVALID_PASSWORD_MSG = 'אחד או יותר מפרטי ההזדהות שמסרת שגויים';
const ACCOUNT_BLOCKED_MSG = 'המנוי חסום';
const AUTH_ERROR_MARKERS = [/actionRequired["\s:]*["\s]*stepup/i, /SME\s*-\s*קלט לא תקין/];

class Exit extends Error {
  constructor(code, msg) { super(msg); this.code = code; }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function opt(name, def) {
  const args = process.argv.slice(2);
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : def;
}

const outDir = path.resolve(opt('--out', dataDir(repo, 'leumi/raw')));
const accountIndex = Number(opt('--account-index', '1'));
const numTx = Number(opt('--num-tx', '500'));
// This customer's two loans (dump-loans.sh's default); re-read #ddlLoans if the loan set changes.
const loanIndices = opt('--loans', '3 4').trim().split(/\s+/).map(Number);
if (![accountIndex, numTx, ...loanIndices].every((n) => Number.isInteger(n) && n > 0)) {
  console.error('--account-index, --num-tx and --loans must be positive integers');
  process.exit(2);
}
const missing = ['LEUMI_USERNAME', 'LEUMI_PASSWORD'].filter((k) => !process.env[k]);
if (missing.length) {
  console.error(`Missing env: ${missing.join(', ')}`);
  process.exit(2);
}

/** Log in; returns once the SPA is up, otherwise throws Exit. */
async function login(page) {
  await page.goto(`${HOST}/authenticate/logon`, { waitUntil: 'networkidle2' });
  await page.waitForSelector('input[placeholder="שם משתמש"]', { visible: true });
  await page.type('input[placeholder="שם משתמש"]', process.env.LEUMI_USERNAME);
  await page.type('input[placeholder="סיסמה"]', process.env.LEUMI_PASSWORD);
  // The gate-keeper page (2026-10) ignores a click on the first button[type=submit]: submit with
  // the enabled "כניסה לחשבון" button itself, else Enter in the password field (one attempt only).
  await sleep(500);
  const submitted = await page.evaluate(() => {
    const b = [...document.querySelectorAll('button')]
      .find((el) => el.innerText.trim() === 'כניסה לחשבון' && !el.disabled && el.offsetParent !== null);
    if (b) b.click();
    return !!b;
  });
  if (!submitted) {
    await page.focus('input[placeholder="סיסמה"]');
    await page.keyboard.press('Enter');
  }

  for (let i = 0; i < 60; i++) {
    await sleep(1000);
    if (/ebanking\/SO\/SPA\.aspx/i.test(page.url()) && (await sessionId(page))) return;
    if (await page.$('form input[name="newPwd"]').catch(() => null)) throw new Exit(3, 'LOGIN FAILED: CHANGE_PASSWORD');
    const text = await page.evaluate(() => document.body?.innerText || '').catch(() => '');
    if (text.includes(INVALID_PASSWORD_MSG)) throw new Exit(3, 'LOGIN FAILED: INVALID_PASSWORD');
    if (text.includes(ACCOUNT_BLOCKED_MSG)) throw new Exit(3, 'LOGIN FAILED: ACCOUNT_BLOCKED');
    if (/קוד אימות|קוד חד[ -]פעמי|נשלח אליך קוד/.test(text)) throw new Exit(3, 'LOGIN FAILED: OTP_REQUIRED');
  }
  // Unrecognised page: keep what it showed (local only) so the next selector fix is a look, not a guess.
  const shot = path.join(outDir, 'login-unknown.png');
  await page.screenshot({ path: shot, fullPage: true }).catch(() => {});
  const text = await page.evaluate(() => document.body?.innerText || '').catch(() => '');
  fs.writeFileSync(path.join(outDir, 'login-unknown.txt'), `${page.url()}\n\n${text}`);
  throw new Exit(1, `LOGIN FAILED: UNKNOWN ${page.url()} (screenshot + text: ${shot}, login-unknown.txt)`);
}

/** The live Broker SessionID: 32-hex suffix of the SPA's "_pouch_sessionDB_<id>" localStorage key. */
const sessionId = (page) => page.evaluate(() => {
  const k = Object.keys(localStorage).find((k) => /_pouch_sessionDB_[0-9a-f]{32}/i.test(k));
  return k ? k.match(/([0-9a-f]{32})/i)[1] : '';
}).catch(() => '');

function writeFile(fname, text) {
  const target = path.join(outDir, fname);
  fs.writeFileSync(`${target}.tmp`, text, 'utf8');
  fs.renameSync(`${target}.tmp`, target);
}

/**
 * Guarded writer (same rules as dump.sh): login-shell HTML, non-JSON and auth-error stubs are
 * not written (previous file kept) and fail the run; Broker's jsonResp string is unwrapped;
 * otherwise pretty JSON, atomic tmp + rename.
 */
const state = { failed: false };
function guardWrite(fname, status, body) {
  const size = String(body.length).padStart(9);
  const reject = (why) => {
    console.log(`  --  ${size}B  ${fname}  <-- ${why}, NOT WRITTEN (previous file kept)`);
    state.failed = true;
    return null;
  };
  if (/^\s*<(!doctype|html)/i.test(body)) return reject('LOGIN-SHELL HTML');
  let parsed;
  try { parsed = JSON.parse(body); } catch { return reject('NOT JSON'); }
  if (parsed && typeof parsed.jsonResp === 'string') {
    try { parsed = { ...parsed, jsonResp: JSON.parse(parsed.jsonResp) }; } catch { /* keep as is */ }
  }
  if (AUTH_ERROR_MARKERS.some((re) => re.test(JSON.stringify(parsed)))) return reject('AUTH-ERROR STUB');
  if (status === 401 || status === 403) return reject(`HTTP ${status}`);
  writeFile(fname, JSON.stringify(parsed, null, 2));
  console.log(`  ${status}  ${size}B  ${fname}${status !== 200 ? '  <-- non-200' : ''}`);
  return parsed;
}

/** POST one Broker module with the live SessionID inside the page. */
async function broker(page, fname, moduleName, fields) {
  const sid = await sessionId(page);
  const { status, body } = await page.evaluate(async (url, moduleName, reqObj) => {
    const r = await fetch(`${url}?moduleName=${moduleName}`, {
      method: 'POST', credentials: 'include',
      headers: { 'content-type': 'application/json; charset=UTF-8', accept: 'application/json' },
      body: JSON.stringify({ moduleName, reqObj: JSON.stringify(reqObj), version: 'Infra_V2.0' }),
    });
    return { status: r.status, body: await r.text() };
  }, BROKER, moduleName, {
    StateName: 'BusinessAccountTrx', ModuleName: moduleName,
    SessionHeader: { SessionID: sid, FIID: 'Leumi' }, ...fields,
  });
  return guardWrite(fname, status, body);
}

async function scrapeAccount(page) {
  console.log('== account ==');
  const accounts = await broker(page, 'accounts.json', 'UC_SO_GetAccounts', {
    ComboMethod: 'true', RequestedAccountTypes: 'CHECKING',
    ExtAccountPermissions: 'General', AccountSegments: '', AccountIndex: accountIndex,
  });
  const summary = await page.evaluate(async (url) => {
    const r = await fetch(url, { credentials: 'include', headers: { accept: 'application/json' } });
    return { status: r.status, body: await r.text() };
  }, `${HOST}/UIApiProxy/v1/digital-retails/mobile/accounts/${accountIndex}/SummaryData`);
  const sum = guardWrite('summary.json', summary.status, summary.body);
  const txns = await broker(page, 'transactions.json', 'UC_SO_27_GetBusinessAccountTrx', {
    RequestType: '', FromDateUTC: '', ToDateUTC: '',
    OperationsNumber: String(numTx), Amount: 0, AmountType1: 0, AmountType2: 0,
    TrxType: '1', ReferenceNumber: '0', BeneficiaryName: '0',
    BeneficiaryBankCode: '0', BeneficiaryBranch: '0', BeneficiaryAccountNumber: '0',
    InvoiceNumber: '0', PeriodType: '0', AccountIndex: accountIndex,
  });
  if (!accounts || !sum || !txns?.jsonResp?.HistoryTransactionsItems) {
    console.error('accounts.json, summary.json and transactions.json (with HistoryTransactionsItems) are required');
    state.failed = true;
  }
}

/** dump-loans.sh: amortization grid + per-loan key/value sections, then raw HTML snapshots. */
async function scrapeLoans(page) {
  console.log('== loans ==');
  const num = (s) => { if (s == null) return null; const n = parseFloat(String(s).replace(/,/g, '').replace(/[^\d.-]/g, '')); return Number.isNaN(n) ? null : n; };
  const kv = (rows) => Object.fromEntries(rows.map((r) => [String(r[0] || '').replace(/:$/, '').trim(), r[1]]));
  const loans = [];
  for (const idx of loanIndices) {
    await page.goto(`${HOST}/eBanking/LoanAndMortgages/AmortizationSchedule.aspx?index=${idx}`, { waitUntil: 'networkidle2' }).catch(() => {});
    await sleep(2500);
    const amort = await page.evaluate(() => {
      const cl = (s) => (s || '').replace(/ /g, ' ').replace(/\s+/g, ' ').trim();
      const t = document.getElementById('Table');
      const sel = document.getElementById('ddlLoans');
      const rows = t ? [...t.querySelectorAll('tr')].map((tr) => [...tr.querySelectorAll('th,td')].map((c) => cl(c.textContent))).filter((r) => r.some((c) => c)) : [];
      return { loan: sel && sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].text.trim() : null, rows };
    });
    const sections = await page.evaluate(async (url) => {
      const cl = (s) => (s || '').replace(/ /g, ' ').replace(/\s+/g, ' ').trim();
      const r = await fetch(url, { credentials: 'include' });
      const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
      const out = {};
      [...doc.querySelectorAll('table')].forEach((t) => {
        const rows = [...t.querySelectorAll('tr')].map((tr) => [...tr.querySelectorAll('th,td')].map((c) => cl(c.textContent))).filter((r) => r.some((c) => c));
        if (rows.length >= 2 && rows.length <= 10 && /^(מידע כללי|יתרות|ריביות|תאריכים)$/.test(rows[0][0])) {
          out[rows[0][0]] = rows.slice(1).filter((r) => r.length >= 2).map((r) => [r[0], r[1]]);
        }
      });
      return out;
    }, `${HOST}/eBanking/LoanAndMortgages/DisplayLoanActivity.aspx?index=${idx}`);
    const [hdr, ...body] = amort.rows.length ? amort.rows : [[]];
    const installments = body.map((r) => ({
      paymentDate: r[0], principal: num(r[1]), interest: num(r[2]), balanceAfter: num(r[3]), totalPayment: num(r[4]),
    })).filter((x) => x.paymentDate && /\d{2}\/\d{2}\/\d{2}/.test(x.paymentDate));
    loans.push({
      index: idx, loanLabel: amort.loan, header: hdr,
      generalInfo: kv(sections['מידע כללי'] || []),
      balances: kv(sections['יתרות'] || []),
      interest: kv(sections['ריביות'] || []),
      dates: kv(sections['תאריכים'] || []),
      installmentCount: installments.length, installments,
    });
    console.log(`  loan ${String(amort.loan || '').trim()}  index=${idx}  ${installments.length} installments`);
  }
  // Stub guard: a lapsed session renders no loan pages, so every loan comes back without a number.
  // The pages share server-side state: two indexes can render the same loan (2026-10-27).
  const numbers = loans.map((l) => l.generalInfo['מספר הלוואה']);
  if (new Set(numbers).size !== numbers.length) {
    console.log(`  --  loans.json  <-- SAME LOAN ON TWO PAGES (${numbers.join(', ')}), NOT WRITTEN (previous file kept)`);
    return;
  }
  if (loans.some((l) => !l.generalInfo['מספר הלוואה'])) {
    console.log('  --  loans.json  <-- NO LOAN DETAIL (session or loan set changed), NOT WRITTEN (previous file kept)');
    state.failed = true;
    return;
  }
  writeFile('loans.json', JSON.stringify({ source: 'hb2.bankleumi.co.il - LoanAndMortgages', capturedAt: new Date().toISOString(), loans }, null, 2));

  const html = await page.evaluate(async (host, indices) => {
    const out = {};
    out['loan-summary'] = await (await fetch(`${host}/eBanking/LoanAndMortgages/DisplayLoansAndMortgagesSummary.aspx?from=sideMenu`, { credentials: 'include' })).text();
    for (const idx of indices) out[`loan-activity-${idx}`] = await (await fetch(`${host}/eBanking/LoanAndMortgages/DisplayLoanActivity.aspx?index=${idx}`, { credentials: 'include' })).text();
    return out;
  }, HOST, loanIndices);
  for (const [k, text] of Object.entries(html)) {
    writeFile(`${k}.html`, text);
    console.log(`  ${k}.html  ${text.length}B`);
  }
}

console.log(`Out dir : ${outDir}`);
console.log('----------------------------------------');
fs.mkdirSync(outDir, { recursive: true });
const browser = await puppeteer.launch({ headless: true });
let code = 0;
try {
  const page = await browser.newPage();
  await page.setCacheEnabled(false);
  await page.setViewport({ width: 1280, height: 900 });
  await login(page);
  await scrapeAccount(page);   // Broker calls first: they need the SPA's live SessionID
  await scrapeLoans(page);     // navigates away from the SPA
  if (state.failed) code = 1;
} catch (e) {
  if (!(e instanceof Exit)) throw e;
  console.error(e.message);
  code = e.code;
} finally {
  await browser.close();
}
console.log('----------------------------------------');
process.exit(code);
