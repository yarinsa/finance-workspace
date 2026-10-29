#!/usr/bin/env node
// Deterministic American Express Israel (Isracard/ICC) scrape: logs in headless by itself
// (puppeteer) with AMEX_ID / AMEX_CARD6_DIGITS / AMEX_PASSWORD from <repo>/.env, then writes the
// same raw files as .claude/skills/amex-refresh/scripts/dump.sh to data/amex/raw/.
//
// Login: we fill and submit the site's own password form on he.americanexpress.co.il instead of
// POSTing the JSON calls ourselves (israeli-bank-scrapers' way). The form sends the page's
// __RequestVerificationToken and, once the server asks for it, a reCAPTCHA v3 token, which a
// hand-built request cannot. We only READ the form's ProxyRequestHandler responses to classify:
//   ValidateIdDataNoReg -> IsRegisterNoReg -> performLogonA (status "1" = logged in).
//
// Data: navigate the web.americanexpress.co.il SPA to /transactions and capture the
// DigitalV3.Transactions POSTs it makes itself, then pull per-card monthly
// GetTransactionsList with the SPA's own request headers.
import puppeteer from 'puppeteer';
import dotenv from 'dotenv';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadEnv, dataDir } from '../tenant.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '../..');
loadEnv(repo, dotenv);

const LOGIN_URL = 'https://he.americanexpress.co.il/personalarea/login/';
const WEB = 'https://web.americanexpress.co.il';
const TX_API = `${WEB}/ocp/transactions/DigitalV3.Transactions`;

// Bootstrap methods the SPA calls on /transactions -> file (same map as dump.sh).
const FILES = {
  GetCardList: 'cardList.json',
  GetTransactionsList: 'transactionsList.json',
  InitContent: 'initContent.json',
  GetPersonalComponents: 'personalComponents.json',
  GetCampaign: 'campaign.json',
};

class Exit extends Error {
  constructor(code, msg) { super(msg); this.code = code; }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const isHtml = (body) => /^\s*<(!doctype|html)/i.test(body);

function opt(name, def) {
  const args = process.argv.slice(2);
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : def;
}

const outDir = path.resolve(opt('--out', dataDir(repo, 'amex/raw')));
const months = opt('--months', '2'); // dump.sh pulls the current + previous billing month
if (!/^\d+$/.test(months) || Number(months) <= 0) {
  console.error('--months must be a positive integer');
  process.exit(2);
}
const missing = ['AMEX_ID', 'AMEX_CARD6_DIGITS', 'AMEX_PASSWORD'].filter((k) => !process.env[k]);
if (missing.length) {
  console.error(`Missing env: ${missing.join(', ')}`);
  process.exit(2);
}

let failed = false;
fs.mkdirSync(outDir, { recursive: true });

/** Keep what the page showed, so the next fix is not a blind retry against a live account. */
async function saveUnknown(page, tag, extra = '') {
  await page.screenshot({ path: path.join(outDir, `${tag}.png`), fullPage: true }).catch(() => {});
  const text = await page.evaluate(() => document.body.innerText).catch(() => '');
  fs.writeFileSync(path.join(outDir, `${tag}.txt`), `URL: ${page.url()}\n${extra}\n\n${text}`, 'utf8');
}

async function visible(page, selector) {
  return page.$eval(selector, (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length))
    .catch(() => false);
}

/**
 * ValidateIdDataNoReg returnCode -> failure reason (from the site's LoginController:
 * "1" go on, "4"/"49" password expired / no password, "5" locked, "7" not registered for
 * password login, anything else is the server's "wrong details" message).
 */
function validateFailure(code) {
  if (code === '4' || code === '49') return 'CHANGE_PASSWORD';
  if (code === '5') return 'ACCOUNT_BLOCKED';
  return 'INVALID_PASSWORD';
}

/** Fill and submit the password form, then classify from the login API responses. */
async function login(page) {
  const seen = {}; // reqName -> parsed JSON response (never the request: it holds the password)
  const order = [];
  page.on('response', async (r) => {
    const m = r.url().match(/ProxyRequestHandler\.ashx\?reqName=([A-Za-z0-9_]+)/);
    if (!m || r.request().method() !== 'POST') return;
    order.push(`${m[1]}:${r.status()}`);
    try { seen[m[1]] = JSON.parse(await r.text()); } catch { seen[m[1]] = { unparsable: true }; }
  });

  // The login page is sometimes slow to render its form (seen 2026-10-25 in a scheduled run).
  // Nothing is typed yet, so loading it a second time cannot count as a failed login.
  for (let attempt = 1; ; attempt++) {
    await page.goto(LOGIN_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
    const ok = await page.waitForSelector('#otpLoginId_ID', { timeout: 30000 }).then(() => true, () => false);
    if (ok) break;
    if (attempt === 2) throw new Exit(1, `login form did not render at ${page.url()} (page not loaded; nothing typed)`);
  }
  await sleep(1500); // let Angular bind the form
  // The card shows the SMS face first; #flip turns it to the permanent-password face.
  if (await visible(page, '#flip')) await page.$eval('#flip', (el) => el.click());
  await sleep(800);
  if (await page.$('#radioID2')) await page.$eval('#radioID2', (el) => { if (!el.checked) el.click(); });

  await page.type('#otpLoginId_ID', process.env.AMEX_ID);
  await page.type('#cardnum', process.env.AMEX_CARD6_DIGITS);
  await page.type('#otpLoginPwd', process.env.AMEX_PASSWORD);
  const submit = 'form[ng-submit*="initPasswordLogin"] button[type=submit]';
  if (!(await page.$(submit))) {
    await saveUnknown(page, 'login-unknown', 'password form submit button not found');
    throw new Exit(1, `LOGIN FAILED: UNKNOWN form changed (page saved to ${outDir}/login-unknown.*)`);
  }
  await page.$eval(submit, (el) => el.click());

  const fail = (reason, note = '') => new Exit(3, `LOGIN FAILED: ${reason}${note ? ` (${note})` : ''}`);
  for (let i = 0; i < 60; i++) {
    await sleep(1000);
    const url = page.url();
    const v = seen.ValidateIdDataNoReg;
    if (v) {
      const status = v.Header?.Status;
      const code = v.ValidateIdDataNoRegBean?.returnCode;
      if (status !== undefined && status !== '1') break; // general error -> unknown, saved below
      if (code && code !== '1') throw fail(validateFailure(code), `ValidateIdDataNoReg returnCode ${code}`);
    }
    if (seen.IsRegisterNoReg?.IsRegisterNoRegBean?.returnCode === '7') {
      throw fail('INVALID_PASSWORD', 'IsRegisterNoReg returnCode 7: no permanent password registered');
    }
    const logonName = Object.keys(seen).find((k) => /^performLogon/i.test(k));
    const logon = logonName && seen[logonName];
    // Success redirects to the web app (seen 2026-10-25: .../StatusPage) so fast that the
    // performLogonA body is often unreadable; landing there after the logon call IS the success.
    if (logonName && url.startsWith(WEB) && !/login|http-errors/i.test(url)) return;
    if (logon && !logon.unparsable) {
      if (logon.status === '1') return; // logged in; the page now redirects to web.americanexpress
      if (logon.status === '3') throw fail('CHANGE_PASSWORD', `${logonName} status 3`);
      if (logon.status === '2' && logon.returnCode === '665') throw fail('ACCOUNT_BLOCKED', 'fraud monitor (665)');
      if (logon.status) throw fail('INVALID_PASSWORD', `${logonName} status ${logon.status}`);
    }
    if (/connectionIssue/i.test(url)) throw fail('ACCOUNT_BLOCKED', 'redirected to connectionIssue');
    if (/RenewPassword/i.test(url)) throw fail('CHANGE_PASSWORD', 'redirected to RenewPassword');
    if (await visible(page, '#otpInput')) throw fail('OTP_REQUIRED');
    // A visible reCAPTCHA challenge also needs a human; reported under the needs-a-human marker.
    if (await visible(page, 'iframe[src*="recaptcha"][src*="bframe"]')) {
      throw fail('OTP_REQUIRED', 'reCAPTCHA challenge shown: a human must log in');
    }
  }
  await saveUnknown(page, 'login-unknown', `login responses seen: ${order.join(', ') || 'none'}`);
  throw new Exit(1, `LOGIN FAILED: UNKNOWN ${page.url()} (page saved to ${outDir}/login-unknown.*)`);
}

/** Validate one response body; write pretty JSON atomically, or reject (previous file kept). */
function write(fname, status, body) {
  const size = String(body.length).padStart(9);
  const reject = (why) => {
    console.log(`  --  ${size}B  ${fname}  <-- ${why}, NOT WRITTEN (previous file kept)`);
    failed = true;
    return null;
  };
  if (isHtml(body)) return reject('LOGIN-SHELL HTML');
  let parsed;
  try { parsed = JSON.parse(body); } catch { return reject('NOT JSON'); }
  if (status !== 200) return reject(`HTTP ${status}`);
  const target = path.join(outDir, fname);
  fs.writeFileSync(`${target}.tmp`, JSON.stringify(parsed, null, 2), 'utf8');
  fs.renameSync(`${target}.tmp`, target);
  console.log(`  ${status}  ${size}B  ${fname}`);
  return parsed;
}

/** Navigate the SPA to /transactions and capture its own DigitalV3.Transactions POSTs. */
async function captureBootstrap(page) {
  const captured = {};
  let spaHeaders = null; // the SPA's own GetTransactionsList request headers, replayed per card
  let capturing = true;
  page.on('response', async (r) => {
    if (!capturing) return;
    const m = r.url().match(/DigitalV3\.Transactions\/(\w+)$/);
    if (!m || r.request().method() !== 'POST') return;
    if (m[1] === 'GetTransactionsList' && !spaHeaders) spaHeaders = r.request().headers();
    try { captured[m[1]] = { status: r.status(), body: await r.text() }; } catch {}
  });
  await page.goto(`${WEB}/transactions`, { waitUntil: 'networkidle2', timeout: 60000 }).catch(() => {});
  for (let i = 0; i < 20 && !(captured.GetCardList && captured.GetTransactionsList); i++) await sleep(1000);
  await sleep(3000); // late widgets (campaign, personal components)
  capturing = false;
  return { captured, spaHeaders };
}

/** Is the web.americanexpress session live? (dump.sh's check_session.sh signal: GET /IsLoggedIn.) */
async function isLoggedIn(page) {
  return page.evaluate(async (u) => {
    const r = await fetch(u, { credentials: 'include' });
    const t = await r.text();
    return r.status === 200 && !/^\s*<(!doctype|html)/i.test(t);
  }, `${WEB}/IsLoggedIn`).catch(() => false);
}

// Headers a replay may set itself (the browser/Node owns the rest).
const DROP_HEADERS = /^(host|content-length|cookie|origin|referer|user-agent|connection|accept-encoding|sec-.*)$/i;

/**
 * POST one per-card GetTransactionsList. First from inside the page (fetch carries the context's
 * cookies, HttpOnly included, for same-origin requests); if that comes back as login-shell HTML,
 * fall back to Node with the context's cookies as a Cookie header (dump.sh's page.request.post).
 */
function makePoster(page, spaHeaders) {
  const headers = { accept: 'application/json, text/plain, */*', 'content-type': 'application/json' };
  for (const [k, v] of Object.entries(spaHeaders || {})) if (!DROP_HEADERS.test(k)) headers[k] = v;
  let mode = 'page';
  async function viaNode(data) {
    const cookies = await page.cookies(WEB);
    const ua = await page.evaluate(() => navigator.userAgent);
    const r = await fetch(`${TX_API}/GetTransactionsList`, {
      method: 'POST',
      headers: { ...headers, cookie: cookies.map((c) => `${c.name}=${c.value}`).join('; '),
        origin: WEB, referer: `${WEB}/transactions`, 'user-agent': ua },
      body: JSON.stringify(data),
    });
    return { status: r.status, body: await r.text() };
  }
  return async function post(data) {
    if (mode === 'page') {
      const res = await page.evaluate(async (u, h, d) => {
        const r = await fetch(u, { method: 'POST', credentials: 'include', headers: h, body: JSON.stringify(d) });
        return { status: r.status, body: await r.text() };
      }, `${TX_API}/GetTransactionsList`, headers, data);
      if (!isHtml(res.body)) return res;
      console.log('  (in-page fetch got login-shell HTML; switching to Node with the cookie jar)');
      mode = 'node';
    }
    return viaNode(data);
  };
}

/**
 * [{tag: 'MM-YYYY', billingMonth: '01/MM/YYYY'}] for next month, this month and the n-1 before it.
 * A billing month holds the purchases since the previous statement, so purchases made after this
 * month's statement only appear under NEXT month's bill.
 */
function billingMonths(n) {
  const now = new Date();
  return Array.from({ length: n + 1 }, (_, i) => i - 1).map((back) => {
    const d = new Date(now.getFullYear(), now.getMonth() - back, 1);
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    return { tag: `${mm}-${d.getFullYear()}`, billingMonth: `01/${mm}/${d.getFullYear()}` };
  });
}

const browser = await puppeteer.launch({ headless: true });
let code = 0;
try {
  const page = await browser.newPage();
  await page.setCacheEnabled(false);
  await page.setViewport({ width: 1280, height: 900 });
  const ua = await browser.userAgent();
  await page.setUserAgent(ua.replace('HeadlessChrome/', 'Chrome/'));
  // Same as israeli-bank-scrapers: never load the site's headless-browser detector.
  await page.setRequestInterception(true);
  page.on('request', (req) => {
    if (req.isInterceptResolutionHandled()) return;
    if (req.url().includes('detector-dom.min.js')) req.abort();
    else req.continue();
  });

  await login(page);
  console.log(`Out dir : ${outDir}`);
  console.log('----------------------------------------');

  const { captured, spaHeaders } = await captureBootstrap(page);
  if (!captured.GetCardList) {
    const live = await isLoggedIn(page);
    await saveUnknown(page, 'capture-unknown', `IsLoggedIn: ${live ? 'LIVE' : 'NOT LIVE'}`);
    throw new Exit(1, live
      ? 'Session is LIVE but GetCardList was not captured: the AMEX SPA route or DigitalV3 methods moved'
      : 'session not live after a successful login (page saved to capture-unknown.*)');
  }
  console.log('== /transactions bootstrap ==');
  const parsed = {};
  for (const [method, fname] of Object.entries(FILES)) {
    const c = captured[method];
    if (!c) { console.log(`  --      not captured  ${fname}  (previous file kept)`); continue; }
    parsed[method] = write(fname, c.status, c.body);
  }
  const cardList = parsed.GetCardList;
  if (!cardList) throw new Exit(1, 'cardList.json is required (normalize.py reads it)');

  const cards = (cardList.data?.cardsList || []).filter((c) => c.isActive)
    .map((c) => ({ cardSuffix: c.cardSuffix, companyCode: c.companyCode }));
  if (!cards.length) throw new Exit(1, 'no active card in cardList.json');

  console.log(`== per-card transactions (${cards.length} active card(s), ${months} month(s)) ==`);
  const post = makePoster(page, spaHeaders);
  let any = false;
  for (const c of cards) {
    for (const { tag, billingMonth } of billingMonths(Number(months))) {
      // Body exactly as dump.sh sends it (recovered from the SPA's own POST, 2026-09-18).
      // companyCode is a string in cardList, so isPartner is true here as it is in dump.sh.
      const data = {
        card4Number: c.cardSuffix, isNextBillingDate: true, cardStatus: 0, billingMonth,
        companyCode: c.companyCode, isPartner: c.companyCode !== 77,
      };
      const { status, body } = await post(data);
      if (write(`transactions_${c.cardSuffix}_${tag}.json`, status, body)) any = true;
    }
  }
  if (!any) {
    console.error('no transactions_<suffix>_<MM-YYYY>.json was written');
    failed = true;
  }
} catch (e) {
  if (!(e instanceof Exit)) throw e;
  console.error(e.message);
  code = e.code;
} finally {
  await browser.close();
}
console.log('----------------------------------------');
process.exit(code || (failed ? 1 : 0));
