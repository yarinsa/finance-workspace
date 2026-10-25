#!/usr/bin/env node
// Deterministic Harel scrape, headless. Harel's only login is ID + phone + a one-time code (SMS or
// email). By default this does NOT log in: it reuses the session the human left in the Chrome
// profile ~/.chrome-cdp-harel (port 9227). With --login (only from a sync the human started in the
// app) it fills HAREL_ID / HAREL_PHONE from .env, asks for an SMS, and waits for the code the HUMAN
// typed in the app, which the sync worker drops into --otp-file. It never reads SMS or email itself.
//   - Chrome on 9227 is up  -> connect over CDP and work in a new tab of it (the profile is locked).
//   - otherwise             -> launch the same Google Chrome binary headless on that profile (the
//                              same binary, so it can decrypt the profile's Keychain-encrypted cookies).
// Then it loads client-view.aspx, recovers the per-page-load `ticket` from the page's own XHRs, and
// writes the same files as harel-refresh/scripts/dump.sh to data/harel/raw/.
//
//   node scrapers/harel/scrape.mjs [--out DIR] [--check] [--login --otp-file PATH]
//     --check     only report whether the session is live (writes nothing)
//     --login     log in when the session lapsed; the code is read once from --otp-file
//                 (then deleted). A rejected code is never resubmitted.
//
// Exit codes: 0 ok / live; 1 failure (retryable); 2 bad args;
// 3 LOGIN FAILED: SESSION_EXPIRED | OTP_TIMEOUT | OTP_REJECTED | LOGIN_ERROR (a human must act;
//   never retried).
import puppeteer from 'puppeteer';
import dotenv from 'dotenv';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '../..');
dotenv.config({ path: path.join(repo, '.env'), quiet: true });

const PORT = 9227;
const PROFILE = path.join(os.homedir(), '.chrome-cdp-harel');
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORTAL = 'https://www.harel-group.co.il';
const CLIENT_VIEW = `${PORTAL}/personal-info/my-harel/Pages/client-view.aspx`;
const API = 'https://digital.harel-group.co.il/apps.client-view/client-view';
// Fixed, named endpoint list (same as dump.sh); customer-products is what validate.py requires.
const ENDPOINTS = ['online-data', 'customer-products', 'client-claims-by-area', 'client-requests'];

class Exit extends Error {
  constructor(code, msg) { super(msg); this.code = code; }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const args = process.argv.slice(2);
function opt(name, def) {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : def;
}
const checkOnly = args.includes('--check');
const doLogin = args.includes('--login');
const otpFile = opt('--otp-file', '');
const outDir = path.resolve(opt('--out', path.join(repo, 'data/harel/raw')));
const OTP_WAIT_MS = 8 * 60_000;  // inside the sync's 10-minute scrape timeout
const DEBUG_DIR = path.join(os.tmpdir(), 'harel-login-debug');
if (doLogin) {
  if (!otpFile) { console.error('--login needs --otp-file'); process.exit(2); }
  const missing = ['HAREL_ID', 'HAREL_PHONE'].filter((k) => !process.env[k]);
  if (missing.length) { console.error(`Missing env: ${missing.join(', ')}`); process.exit(2); }
}

async function cdpUp() {
  try {
    const r = await fetch(`http://127.0.0.1:${PORT}/json/version`, { signal: AbortSignal.timeout(2000) });
    return r.ok;
  } catch {
    return false;
  }
}

/** {browser, page, done}: a tab in the human's Chrome, or a headless Chrome on the same profile. */
async function open() {
  if (await cdpUp()) {
    // 127.0.0.1, never localhost (IPv6 ::1 refuses, see harel-refresh gotchas).
    const browser = await puppeteer.connect({ browserURL: `http://127.0.0.1:${PORT}`, defaultViewport: null });
    const page = await browser.newPage();
    return { page, done: async () => { await page.close().catch(() => {}); await browser.disconnect(); } };
  }
  if (!fs.existsSync(PROFILE)) throw new Exit(3, `LOGIN FAILED: SESSION_EXPIRED (no profile at ${PROFILE})`);
  const browser = await puppeteer.launch({
    headless: true, executablePath: CHROME, userDataDir: PROFILE,
    args: ['--no-first-run', '--no-default-browser-check'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  return { page, done: () => browser.close() };
}

/**
 * Load client-view and wait for its first API call: that URL carries the live ticket. Landing on
 * Login.aspx means the session lapsed. Never navigate with networkidle: the portal keeps
 * connections open and it never settles.
 */
async function ticket(page) {
  let found = '';
  page.on('request', (req) => {
    const m = !found && req.url().startsWith(API) && req.url().match(/ticket=([0-9a-f]{40})/i);
    if (m) found = m[1];
  });
  await page.goto(CLIENT_VIEW, { waitUntil: 'domcontentloaded', timeout: 60000 });
  for (let i = 0; i < 45 && !found; i++) {
    if (onLoginPage(page)) throw new Exit(3, 'LOGIN FAILED: SESSION_EXPIRED');
    await sleep(1000);
  }
  if (!found) {
    if (onLoginPage(page)) throw new Exit(3, 'LOGIN FAILED: SESSION_EXPIRED');
    throw new Exit(1, `no ticket after 45s on ${page.url()}`);
  }
  return found;
}

const onLoginPage = (page) => /\/login-page\/|Login\.aspx/i.test(page.url());

async function visible(page, selector) {
  return page.$eval(selector, (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length))
    .catch(() => false);
}

/** Keep what the page showed, so the next fix is not a blind retry against a live login. */
async function saveDebug(page) {
  fs.mkdirSync(DEBUG_DIR, { recursive: true });
  await page.screenshot({ path: path.join(DEBUG_DIR, 'page.png') }).catch(() => {});
  fs.writeFileSync(path.join(DEBUG_DIR, 'page.txt'), await page.evaluate(() => document.body.innerText).catch(() => ''));
  return DEBUG_DIR;
}

/** Click the visible submit button whose text matches `re` (Harel's buttons have no ids). */
async function clickButton(page, re) {
  const ok = await page.evaluate((src) => {
    const re = new RegExp(src);
    const b = [...document.querySelectorAll('button')].find((e) =>
      (e.offsetWidth || e.offsetHeight) && re.test((e.innerText || '').trim()));
    if (b) b.click();
    return !!b;
  }, re.source);
  if (!ok) throw new Exit(1, `no "${re.source}" button (page saved to ${await saveDebug(page)})`);
}

/** Visible inputs of the code step: one field, or one box per digit. */
async function otpInputs(page) {
  return page.evaluate(() => {
    const els = [...document.querySelectorAll('input')].filter((e) =>
      !['uid', 'phone'].includes(e.id) && !['hidden', 'radio', 'checkbox', 'submit', 'button'].includes(e.type)
      && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
    return els.map((e, i) => { e.setAttribute('data-harel-otp', String(i)); return `[data-harel-otp="${i}"]`; });
  });
}

/** Wait for the code the human typed in the app; read it once and delete it. */
async function waitForCode() {
  const end = Date.now() + OTP_WAIT_MS;
  while (Date.now() < end) {
    try {
      const code = fs.readFileSync(otpFile, 'utf8').trim();
      fs.rmSync(otpFile, { force: true });
      if (/^\d{4,8}$/.test(code)) return code;
    } catch {}
    await sleep(1000);
  }
  throw new Exit(3, 'LOGIN FAILED: OTP_TIMEOUT (no code was entered in the app)');
}

/** ID + phone -> SMS -> the code from the app. Leaves the page logged in (or throws). */
async function login(page) {
  if (!onLoginPage(page)) await page.goto(`${PORTAL}/Pages/login-page/Login.aspx?LoginOriginatingAction=PersonalInfoPage&isshowlogin=true&Source=%2fpersonal-info%2fmy-harel%2fPages%2fclient-view.aspx`,
    { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForSelector('#uid', { visible: true, timeout: 30000 });
  for (const [sel, v] of [['#uid', process.env.HAREL_ID], ['#phone', process.env.HAREL_PHONE]]) {
    await page.$eval(sel, (el) => { el.value = ''; });
    await page.type(sel, v);
  }
  if (await visible(page, '#otp-channel-sms')) await page.$eval('#otp-channel-sms', (el) => el.click());
  await clickButton(page, /^המשך$/);

  // The code step replaces the form (the uid field goes away and a code field appears).
  let boxes = [];
  for (let i = 0; i < 30 && !boxes.length; i++) {
    await sleep(1000);
    if (!(await visible(page, '#uid'))) boxes = await otpInputs(page);
  }
  if (!boxes.length) {
    throw new Exit(3, `LOGIN FAILED: LOGIN_ERROR (no code step after ID + phone; page saved to ${await saveDebug(page)})`);
  }
  console.log('OTP_REQUESTED');  // the code is on its way to the phone
  const code = await waitForCode();
  if (boxes.length >= code.length && boxes.length > 1) {
    for (let i = 0; i < code.length; i++) await page.type(boxes[i], code[i]);
  } else {
    await page.type(boxes[0], code);
  }
  await clickButton(page, /כניסה|המשך|אישור|שליחה/).catch(() => page.keyboard.press('Enter'));
  for (let i = 0; i < 30; i++) {
    await sleep(1000);
    if (!onLoginPage(page)) return;
  }
  // Still on the login page: wrong or expired code. Never resubmit: that asks for another SMS.
  throw new Exit(3, `LOGIN FAILED: OTP_REJECTED (page saved to ${await saveDebug(page)})`);
}

let failed = false;

/** Fetch one endpoint in the page; reject HTML / non-JSON / non-200 (previous file kept), else write atomically. */
async function dump(page, name, query) {
  const fname = `${name}.json`;
  const { status, body } = await page.evaluate(async (url) => {
    const r = await fetch(url, { credentials: 'include', headers: { accept: 'application/json' } });
    return { status: r.status, body: await r.text() };
  }, `${API}/${name}?${query}`);
  const size = String(body.length).padStart(9);
  const reject = (why) => {
    console.log(`  --  ${size}B  ${fname}  <-- ${why}, NOT WRITTEN (previous file kept)`);
    failed = true;
  };
  if (/^\s*<(!doctype|html)/i.test(body)) return reject('LOGIN-SHELL HTML');
  let parsed;
  try { parsed = JSON.parse(body); } catch { return reject('NOT JSON'); }
  if (status !== 200) return reject(`HTTP ${status}`);
  const target = path.join(outDir, fname);
  fs.writeFileSync(`${target}.tmp`, JSON.stringify(parsed, null, 2), 'utf8');
  fs.renameSync(`${target}.tmp`, target);
  console.log(`  ${status}  ${size}B  ${fname}`);
}

let code = 0;
let session;
try {
  session = await open();
  let t;
  try {
    t = await ticket(session.page);
  } catch (e) {
    if (!(doLogin && e instanceof Exit && e.message === 'LOGIN FAILED: SESSION_EXPIRED')) throw e;
    await login(session.page);
    t = await ticket(session.page);
  }
  if (checkOnly) {
    console.log('VERDICT: LIVE');
  } else {
    fs.mkdirSync(outDir, { recursive: true });
    console.log(`Out dir : ${outDir}`);
    console.log(`ticket  : ${t.slice(0, 8)}… (rotates per run)`);
    console.log('----------------------------------------');
    const q = `ctime=${Date.now()}&ticket=${t}`;
    for (const name of ENDPOINTS) await dump(session.page, name, q);
    console.log('----------------------------------------');
  }
} catch (e) {
  if (!(e instanceof Exit)) throw e;
  console.error(e.message);
  if (checkOnly && e.code === 3) console.log('VERDICT: LOGGED_OUT');
  code = e.code;
} finally {
  await session?.done();
}
process.exit(code || (failed ? 1 : 0));
