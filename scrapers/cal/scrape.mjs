#!/usr/bin/env node
// Deterministic CAL (cal-online) scrape: logs in by itself, headless, with CAL_USERNAME /
// CAL_PASSWORD from <repo>/.env (same flow as israeli-bank-scrapers' visaCal scraper), then
// calls the same api.cal-online.co.il endpoints as .claude/skills/refresh/scripts/cal/dump.sh
// and writes the same raw files to data/cal/raw. No Chrome/CDP session needed.
//
// Exit codes: 0 ok · 1 failure (retryable) · 2 missing env / bad args ·
// 3 LOGIN FAILED (wrong password, password renewal or OTP demanded): needs a human, do not retry.
import puppeteer from 'puppeteer';
import dotenv from 'dotenv';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadEnv, dataDir } from '../tenant.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '../..');
loadEnv(repo, dotenv);

const LOGIN_URL = 'https://www.cal-online.co.il/';
const HOST = 'https://api.cal-online.co.il';
const SITE_ID = '09031987-273E-2311-906C-8AF85B17C8D9'; // static web-client id
const INVALID_PASSWORD_MSG = 'שם המשתמש או הסיסמה שהוזנו שגויים';
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

const outDir = path.resolve(opt('--out', dataDir(repo, 'cal/raw')));
const missing = ['CAL_USERNAME', 'CAL_PASSWORD'].filter((k) => !process.env[k]);
if (missing.length) {
  console.error(`Missing env: ${missing.join(', ')}`);
  process.exit(2);
}

/** The login form lives in an iframe served from connect.cal-online.co.il (index.html -> send-otp). */
async function loginFrame(page) {
  for (let i = 0; i < 30; i++) {
    const f = page.frames().find((fr) => fr.url().includes('connect.cal-online'));
    if (f) return f;
    await sleep(1000);
  }
  throw new Exit(1, 'LOGIN: login iframe never appeared');
}

/** Poll for a selector in a frame that may still be navigating (waitForSelector dies on it). */
async function waitIn(frame, selector, what, secs = 30) {
  for (let i = 0; i < secs; i++) {
    if (await frame.$(selector).catch(() => null)) return;
    await sleep(1000);
  }
  throw new Exit(1, `LOGIN: ${what} (${selector}) never appeared`);
}

/**
 * Run a frame/page operation, returning `dflt` if it throws. Puppeteer's detached-frame check throws
 * synchronously (before a promise exists), so `.catch()` on `frame.evaluate()` does NOT cover it: the
 * login iframe is torn down the moment login succeeds, which crashed every run (2026-10-30..11-01).
 */
const safe = async (fn, dflt) => { try { return await fn(); } catch { return dflt; } };

/**
 * In-page element.click(). Puppeteer's mouse click waits on a rendered frame and hangs when
 * headless Chrome is not painting (seen with the Mac's display asleep); the DOM click works always.
 */
const domClick = (frame, selector) => safe(() => frame.evaluate((sel) => {
  const el = document.querySelector(sel);
  if (el) el.click();
  return !!el;
}, selector), false);

/** The rotating CALAuthScheme token, written to sessionStorage by the SPA after login. */
const readToken = (page) => page.evaluate(() => {
  try { return JSON.parse(sessionStorage.getItem('auth-module') || '{}')?.auth?.calConnectToken || ''; }
  catch { return ''; }
}).catch(() => '');

/** Save what the browser shows (screenshot best-effort, page + login-frame text) for a human. */
async function saveLoginState(page, frame) {
  fs.mkdirSync(outDir, { recursive: true });
  await Promise.race([
    page.screenshot({ path: path.join(outDir, 'login-unknown.png') }).catch(() => {}),
    sleep(10000),
  ]);
  const pageText = await page.evaluate(() => document.body?.innerText || '').catch(() => '');
  const frameText = frame ? await safe(() => frame.evaluate(() => document.body?.innerText || ''), '') : '';
  fs.writeFileSync(path.join(outDir, 'login-unknown.txt'),
    `page: ${page.url()}\n\n${pageText}\n\n--- login frame: ${frame?.url() || '-'} ---\n${frameText}`, 'utf8');
  console.error(`Saved login-unknown.png / login-unknown.txt to ${outDir}`);
}

/** Log in; returns the live token, otherwise throws Exit. */
async function login(page) {
  await page.goto(LOGIN_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  const title = await page.title().catch(() => '');
  if (/request rejected/i.test(title)) throw new Exit(1, 'LOGIN: cal-online WAF rejected the request (bot block)');
  await page.waitForSelector('#ccLoginDesktopBtn', { visible: true, timeout: 30000 });
  await domClick(page, '#ccLoginDesktopBtn');
  const frame = await loginFrame(page);
  // The iframe opens on the ID + card-digits OTP tab (send-otp); switch to username/password.
  await waitIn(frame, '#regular-login', 'username-login tab');
  await domClick(frame, '#regular-login');
  await waitIn(frame, '[formcontrolname="userName"]', 'username field');
  await waitIn(frame, 'input[type="password"][formcontrolname="password"]', 'password field', 10);
  if (await frame.$('[formcontrolname="id"]')) throw new Exit(1, 'LOGIN: still on the ID/OTP tab, not submitting');
  await frame.type('[formcontrolname="userName"]', process.env.CAL_USERNAME);
  await frame.type('[formcontrolname="password"]', process.env.CAL_PASSWORD);
  // The "כניסה" submit of the form holding the password field (not the OTP or create-user buttons).
  if (!(await domClick(frame, 'form:has([formcontrolname="password"]) button[type="submit"]'))) {
    throw new Exit(1, 'LOGIN: submit button not found');
  }

  for (let i = 0; i < 60; i++) {
    await sleep(1000);
    const url = page.url();
    if (/dashboard/i.test(url)) {
      const token = await readToken(page);
      if (token) return token;
      continue;
    }
    if (/renew|change-?password/i.test(url)) throw new Exit(3, 'LOGIN FAILED: CHANGE_PASSWORD');
    const f = page.frames().find((fr) => fr.url().includes('connect.cal-online'));
    if (!f) continue;
    if (/change-?password/i.test(f.url())) throw new Exit(3, 'LOGIN FAILED: CHANGE_PASSWORD');
    const text = await safe(() => f.evaluate(() => document.body?.innerText || ''), '');
    if (text.includes(INVALID_PASSWORD_MSG)) throw new Exit(3, 'LOGIN FAILED: INVALID_PASSWORD');
    if (/החלפת סיסמה|סיסמה חדשה|תוקף הסיסמה/.test(text)) throw new Exit(3, 'LOGIN FAILED: CHANGE_PASSWORD');
    if (/קוד אימות|קוד חד[ -]פעמי/.test(text) && !(await safe(() => f.$('[formcontrolname="password"]'), null))) {
      throw new Exit(3, 'LOGIN FAILED: OTP_REQUIRED');
    }
    const err = await safe(() => f.evaluate(() =>
      [...document.querySelectorAll('div.general-error > div, .err-desc')].map((e) => e.innerText.trim()).filter(Boolean).join(' | '),
    ), '');
    if (err) {
      await saveLoginState(page, f);
      throw new Exit(3, `LOGIN FAILED: ${err}`);
    }
  }
  await saveLoginState(page, page.frames().find((fr) => fr.url().includes('connect.cal-online')));
  throw new Exit(1, `LOGIN FAILED: UNKNOWN ${page.url()}`);
}

/**
 * Guarded writer (same rules as dump.sh): login-shell HTML, non-JSON and auth-error stubs are
 * not written (previous file kept) and fail the run; otherwise pretty JSON, atomic tmp + rename.
 */
function createDumper(token) {
  const state = { failed: false };
  fs.mkdirSync(outDir, { recursive: true });

  async function dump(page, fname, apiPath, body) {
    const { status, text } = await page.evaluate(async (url, token, siteId, body) => {
      const r = await fetch(url, {
        method: 'POST', credentials: 'include',
        headers: {
          accept: 'application/json, text/plain, */*',
          'content-type': 'application/json',
          authorization: `CALAuthScheme ${token}`,
          'x-site-id': siteId,
        },
        body: JSON.stringify(body || {}),
      });
      return { status: r.status, text: await r.text() };
    }, HOST + apiPath, token, SITE_ID, body);

    const size = String(text.length).padStart(9);
    const reject = (why) => {
      console.log(`  --  ${size}B  ${fname}  <-- ${why}, NOT WRITTEN (previous file kept)`);
      state.failed = true;
      return null;
    };
    if (/^\s*<(!doctype|html)/i.test(text)) return reject('LOGIN-SHELL HTML');
    let parsed;
    try { parsed = JSON.parse(text); } catch { return reject('NOT JSON'); }
    if (AUTH_ERROR_MARKERS.some((re) => re.test(JSON.stringify(parsed)))) return reject('AUTH-ERROR STUB');
    if (status === 401 || status === 403) return reject(`HTTP ${status}`);

    const target = path.join(outDir, fname);
    fs.writeFileSync(`${target}.tmp`, JSON.stringify(parsed, null, 2), 'utf8');
    fs.renameSync(`${target}.tmp`, target);
    console.log(`  ${status}  ${size}B  ${fname}${status !== 200 ? '  <-- non-200' : ''}`);
    return parsed;
  }
  return { dump, state };
}

async function scrape(page, token) {
  const { dump, state } = createDumper(token);

  console.log('== account / cards ==');
  // account/init is the canonical cards source; it replaces dump.sh's sessionStorage["init"] read.
  const init = await dump(page, 'account_init.json', '/Authentication/api/account/init', { tokenGuid: '' });
  const cards = init?.result?.cards || [];
  if (!cards.length) throw new Exit(1, 'account_init.json has no cards: cannot build the card/account ids');
  const cardIds = cards.map((c) => c.cardUniqueId);
  const acct = cards[0].bankAccountUniqueId || '';
  console.log(`Cards   : ${cards.length}`);

  const now = new Date();
  const yearAgo = new Date(now); yearAgo.setFullYear(now.getFullYear() - 1);

  console.log('== billing summary ==');
  const summary = await dump(page, 'monthlyDebitsSummary.json', '/Transactions/api/financeDashboard/getMonthlyDebitsSummary', { bankAccountUniqueId: acct });
  await dump(page, 'bigNumberAndDetails.json', '/Transactions/api/financeDashboard/getBigNumberAndDetails', { bankAccountUniqueId: acct });

  console.log('== transactions (all cards, last 12 months) ==');
  // trnType:6 = both billed + future-dated; caller 'dashboard' keeps the wide window.
  const filtered = await dump(page, 'filteredTransactions.json', '/Transactions/api/filteredTransactions/getFilteredTransactions', {
    bankAccountUniqueID: acct, cards: cardIds.map((id) => ({ cardUniqueID: id })),
    fromTransDate: yearAgo.toISOString(), toTransDate: now.toISOString(),
    merchantHebName: '', merchantHebCity: '', trnType: 6, fromTrnAmt: 0, toTrnAmt: 0,
    transactionsOrigin: 0, transCardPresentInd: 0, walletTranInd: 0, caller: 'dashboard',
  });
  await dump(page, 'lastTransactionsDashboard.json', '/Transactions/api/LastTransactionsForDashboard/LastTransactionsForDashboard', { bankAccountUniqueID: acct, isDesktop: true });

  console.log('== pending / not-yet-billed (clearance requests) ==');
  await dump(page, 'clearanceRequests.json', '/Transactions/api/approvals/getClearanceRequests', { cardUniqueIDArray: cardIds });

  // A billing month holds the purchases since the previous statement, so anything bought after
  // this month's statement is only in NEXT month's details (`_next`, the still-open cycle).
  console.log('== per-card transaction details (current + next billing month) ==');
  const next = new Date(now.getFullYear(), now.getMonth() + 1, 1);
  for (const [i, c] of cards.entries()) {
    for (const [suffix, d] of [['', now], ['_next', next]]) {
      await dump(page, `cardTransactions_${c.last4Digits || 'x'}_${i}${suffix}.json`, '/Transactions/api/transactionsDetails/getCardTransactionsDetails',
        { cardUniqueId: c.cardUniqueId, month: String(d.getMonth() + 1), year: String(d.getFullYear()) });
    }
  }

  console.log('== loans ==');
  const from = new Date(now); from.setMonth(now.getMonth() - 6);
  const to = new Date(now); to.setMonth(now.getMonth() + 2);
  await dump(page, 'custLoans.json', '/LoanDashboard.API/api/Loans/getCustLoans',
    { loanType: 0, bankUniqueId: acct, startDate: from.toISOString(), endDate: to.toISOString() });

  if (!summary || !filtered) {
    console.error('monthlyDebitsSummary.json and filteredTransactions.json are both required');
    state.failed = true;
  }
  return state;
}

console.log(`Out dir : ${outDir}`);
console.log('----------------------------------------');
const browser = await puppeteer.launch({ headless: true });
let code = 0;
try {
  const page = await browser.newPage();
  // cal-online's WAF answers a "HeadlessChrome" user agent with HTTP 400 "Request Rejected".
  await page.setUserAgent((await browser.userAgent()).replace('HeadlessChrome', 'Chrome'));
  await page.setCacheEnabled(false);
  await page.setViewport({ width: 1280, height: 900 });
  const token = await login(page);
  const state = await scrape(page, token);
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
