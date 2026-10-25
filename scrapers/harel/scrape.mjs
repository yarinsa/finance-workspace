#!/usr/bin/env node
// Deterministic Harel scrape, headless. Harel's only login is ID + phone + a one-time code (SMS or
// email), which an agent never handles, so this does NOT log in: it reuses the session the human
// left in the Chrome profile ~/.chrome-cdp-harel (port 9227).
//   - Chrome on 9227 is up  -> connect over CDP and work in a new tab of it (the profile is locked).
//   - otherwise             -> launch the same Google Chrome binary headless on that profile (the
//                              same binary, so it can decrypt the profile's Keychain-encrypted cookies).
// Then it loads client-view.aspx, recovers the per-page-load `ticket` from the page's own XHRs, and
// writes the same files as harel-refresh/scripts/dump.sh to data/harel/raw/.
//
//   node scrapers/harel/scrape.mjs [--out DIR] [--check]
//     --check  only report whether the session is live (writes nothing)
//
// Exit codes: 0 ok / live; 1 failure (retryable); 2 bad args;
// 3 LOGIN FAILED: SESSION_EXPIRED (a human must log in in the Chrome window; never retried).
import puppeteer from 'puppeteer';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '../..');

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
const outDir = path.resolve(opt('--out', path.join(repo, 'data/harel/raw')));

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
    if (/\/login-page\/|Login\.aspx/i.test(page.url())) throw new Exit(3, 'LOGIN FAILED: SESSION_EXPIRED');
    await sleep(1000);
  }
  if (!found) {
    if (/\/login-page\/|Login\.aspx/i.test(page.url())) throw new Exit(3, 'LOGIN FAILED: SESSION_EXPIRED');
    throw new Exit(1, `no ticket after 45s on ${page.url()}`);
  }
  return found;
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
  const t = await ticket(session.page);
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
