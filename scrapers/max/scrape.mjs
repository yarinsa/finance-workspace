#!/usr/bin/env node
// Deterministic Max (ex-Leumi Card) scrape: logs in headless by itself (puppeteer, same flow as
// israeli-bank-scrapers' Max scraper) with MAX_USERNAME / MAX_PASSWORD from <repo>/.env, then
// calls the onlinelcapi API from inside the page and writes raw JSON to data/max/raw/.
import puppeteer from 'puppeteer';
import dotenv from 'dotenv';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadEnv, dataDir } from '../tenant.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '../..');
loadEnv(repo, dotenv);

const BASE_URL = 'https://www.max.co.il';
const API = 'https://onlinelcapi.max.co.il';
const SUCCESS_URL = `${BASE_URL}/homepage/personal`;

class Exit extends Error {
  constructor(code, msg) { super(msg); this.code = code; }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function opt(name, def) {
  const args = process.argv.slice(2);
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : def;
}

const outDir = path.resolve(opt('--out', dataDir(repo, 'max/raw')));
const months = opt('--months', '6');
if (!/^\d+$/.test(months) || Number(months) <= 0) {
  console.error('--months must be a positive integer');
  process.exit(2);
}
const missing = ['MAX_USERNAME', 'MAX_PASSWORD'].filter((k) => !process.env[k]);
if (missing.length) {
  console.error(`Missing env: ${missing.join(', ')}`);
  process.exit(2);
}

async function fillInput(page, selector, value) {
  await page.$eval(selector, (el) => { el.value = ''; });
  await page.type(selector, value);
}

async function visible(page, selector) {
  return page.$eval(selector, (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length))
    .catch(() => false);
}

/**
 * Fill the ID-number field Max adds to the password form after failed attempts: any visible,
 * empty input in app-user-login-form other than username/password. Returns true when filled.
 */
async function fillIdIfAsked(page) {
  const sel = await page.evaluate(() => {
    const el = [...document.querySelectorAll('app-user-login-form input')].find((e) =>
      !['user-name', 'password'].includes(e.id) && e.type !== 'hidden' && !e.value
      && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
    if (!el) return null;
    el.setAttribute('data-max-id-field', '1');
    return '[data-max-id-field="1"]';
  });
  if (!sel) return false;
  if (!process.env.MAX_ID) throw new Exit(3, 'LOGIN FAILED: ID_REQUIRED (set MAX_ID in .env)');
  await fillInput(page, sel, process.env.MAX_ID);
  return true;
}

/** Open the /login page (it replaced the personal-area popup), pick the password tab, submit, classify. */
async function login(page) {
  await page.goto(`${BASE_URL}/login`, { waitUntil: 'networkidle2' });
  await page.waitForSelector('#login-password-link', { visible: true });
  await page.$eval('#login-password-link', (el) => el.click());
  await page.waitForSelector('#user-name', { visible: true });
  await fillInput(page, '#user-name', process.env.MAX_USERNAME);
  await fillInput(page, '#password', process.env.MAX_PASSWORD);
  // The ID tab's "send me a code" button shares the class; app-user-login-form is the password form.
  const submit = () => page.$eval('app-user-login-form .general-button.send-me-code', (el) => el.click());
  await fillIdIfAsked(page);
  await submit();

  let url = '';
  let idSent = false;
  for (let i = 0; i < 40; i++) {
    url = page.url();
    if (url.startsWith(SUCCESS_URL)) return;
    // After failed attempts Max adds an ID-number field to the form ("נבקש למלא את מספר תעודת
    // הזהות שלך"); fill it from MAX_ID and submit once more.
    if (!idSent && await fillIdIfAsked(page)) {
      idSent = true;
      await submit();
      continue;
    }
    if (url.includes('/renew-password')) throw new Exit(3, 'LOGIN FAILED: CHANGE_PASSWORD');
    if (await visible(page, '#popupWrongDetails')) throw new Exit(3, 'LOGIN FAILED: INVALID_PASSWORD');
    if (await visible(page, '#popupCardHoldersLoginError')) throw new Exit(3, 'LOGIN FAILED: LOGIN_ERROR');
    // "פרטי המשתמש שלך ננעלו": locked after wrong attempts; only the human can unlock (never retry).
    if (await page.evaluate(() => document.body.innerText.includes('ננעלו')).catch(() => false)) {
      throw new Exit(3, 'LOGIN FAILED: ACCOUNT_BLOCKED');
    }
    await sleep(1000);
  }
  // Keep what the page showed, so the next fix is not a blind retry against a live account.
  await page.screenshot({ path: path.join(outDir, 'login-unknown.png') }).catch(() => {});
  fs.writeFileSync(path.join(outDir, 'login-unknown.txt'),
    await page.evaluate(() => document.body.innerText).catch(() => ''), 'utf8');
  throw new Exit(1, `LOGIN FAILED: UNKNOWN ${url} (page saved to ${outDir}/login-unknown.*)`);
}

let failed = false;
fs.mkdirSync(outDir, { recursive: true });

/** Fetch one endpoint in the page; reject HTML / non-JSON (previous file kept), else write atomically. */
async function dump(page, fname, url) {
  const { status, body } = await page.evaluate(async (url) => {
    const r = await fetch(url, { credentials: 'include', headers: { accept: 'application/json' } });
    return { status: r.status, body: await r.text() };
  }, url);
  const size = String(body.length).padStart(9);
  const reject = (why) => {
    console.log(`  --  ${size}B  ${fname}  <-- ${why}, NOT WRITTEN (previous file kept)`);
    failed = true;
    return null;
  };
  if (/^\s*<(!doctype|html)/i.test(body)) return reject('LOGIN-SHELL HTML');
  let parsed;
  try { parsed = JSON.parse(body); } catch { return reject('NOT JSON'); }
  if (status !== 200) return reject(`HTTP ${status}`);
  const target = path.join(outDir, fname);
  fs.writeFileSync(`${target}.tmp`, JSON.stringify(parsed, null, 2), 'utf8');
  fs.renameSync(`${target}.tmp`, target);
  console.log(`  ${status}  ${size}B  ${fname}`);
  return parsed;
}

function transactionsUrl(ym) {
  const filterData = {
    userIndex: -1, cardIndex: -1, monthView: true, date: `${ym}-01`,
    dates: { startDate: '0', endDate: '0' }, bankAccount: { bankAccountIndex: -1, cards: null },
  };
  return `${API}/api/registered/transactionDetails/getTransactionsAndGraphs?filterData=${encodeURIComponent(JSON.stringify(filterData))}&firstCallCardIndex=-1`;
}

/** Month keys YYYY-MM from `n-1` months back through next month (future charges/installments). */
function monthKeys(n) {
  const now = new Date();
  const keys = [];
  for (let back = n - 1; back >= -1; back--) {
    const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - back, 1));
    keys.push(d.toISOString().slice(0, 7));
  }
  return keys;
}

const browser = await puppeteer.launch({ headless: true });
let code = 0;
try {
  const page = await browser.newPage();
  await page.setCacheEnabled(false);
  await page.setViewport({ width: 1280, height: 900 });
  await login(page);
  console.log(`Out dir : ${outDir}`);
  console.log('----------------------------------------');
  await dump(page, 'categories.json', `${API}/api/contents/getCategories`);
  let any = false;
  for (const ym of monthKeys(Number(months))) {
    if (await dump(page, `transactions_${ym}.json`, transactionsUrl(ym))) any = true;
  }
  if (!any) {
    console.error('no transactions_*.json was written');
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
