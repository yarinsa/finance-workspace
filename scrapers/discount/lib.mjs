// Shared foundation for the Discount headless scrapers (scrape.mjs, scrape-mortgage.mjs).
// Login flow is the same as israeli-bank-scrapers' Discount scraper; credentials come from
// <repo>/.env only. Importing this module loads .env, so never import it to "just test".
import puppeteer from 'puppeteer';
import dotenv from 'dotenv';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
export const repo = path.resolve(here, '../..');
dotenv.config({ path: path.join(repo, '.env'), quiet: true });

export const BASE_URL = 'https://start.telebank.co.il';
export const GATEWAY = '/Titan/gatewayAPI';

/** Thrown instead of process.exit() inside the browser session, so `finally` closes Chrome. */
export class Exit extends Error {
  constructor(code, msg) { super(msg); this.code = code; }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** `--name value` from argv, else `def`. */
export function opt(name, def) {
  const args = process.argv.slice(2);
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : def;
}

/** Exit 2 (naming the variables, never their values) when a login credential is not set. */
export function requireLoginEnv() {
  const missing = ['DISCOUNT_ID', 'DISCOUNT_PASSWORD', 'DISCOUNT_NUM'].filter((k) => !process.env[k]);
  if (missing.length) {
    console.error(`Missing env: ${missing.join(', ')}`);
    process.exit(2);
  }
}

// Same as the library's fillInput: clear, then type.
async function fillInput(page, selector, value) {
  await page.$eval(selector, (el) => { el.value = ''; });
  await page.type(selector, value);
}

function classifyUrl(url) {
  const u = url.toLowerCase();
  if (/^https:\/\/start\.telebank\.co\.il\/apollo\/(retail|business)\d*\/(#\/my_account_homepage)?$/.test(u)) return 'SUCCESS';
  if (u === `${BASE_URL}/apollo/core/templates/lobby/masterpage.html#/login_page`) return 'INVALID_PASSWORD';
  if (u === `${BASE_URL}/apollo/core/templates/lobby/masterpage.html#/pwd_renew`) return 'CHANGE_PASSWORD';
  return 'UNKNOWN';
}

/**
 * Log in; returns on success, otherwise throws Exit with the right code. `loginPage` is
 * LOGIN_PAGE (personal, lands on retail3) or LOGIN_PAGE_SME (business, lands on business2: the
 * personal session cannot open the SME app, the server logs it out).
 */
export async function login(page, loginPage = 'LOGIN_PAGE') {
  await page.goto(`${BASE_URL}/login/#/${loginPage}`, { waitUntil: 'load' });
  await page.waitForSelector('#tzId');
  await fillInput(page, '#tzId', process.env.DISCOUNT_ID);
  await fillInput(page, '#tzPassword', process.env.DISCOUNT_PASSWORD);
  // The SME form has no account-number field (ID + password only).
  if (await page.$('#aidnum')) await fillInput(page, '#aidnum', process.env.DISCOUNT_NUM);
  await page.$eval('.sendBtn', (el) => el.click());
  try {
    await page.waitForNavigation();
  } catch {
    await page.waitForSelector('#general-error', { timeout: 100 }).catch(() => {});
  }
  let result = 'UNKNOWN';
  let url = '';
  for (let i = 0; i < 30; i++) {
    url = await page.evaluate(() => window.location.href);
    result = classifyUrl(url);
    if (result !== 'UNKNOWN') break;
    await sleep(1000);
  }
  if (result === 'SUCCESS') return;
  if (result === 'INVALID_PASSWORD' || result === 'CHANGE_PASSWORD') {
    throw new Exit(3, `LOGIN FAILED: ${result}`);
  }
  throw new Exit(1, `LOGIN FAILED: UNKNOWN ${url}`);
}

// `actionRequired` is either "stepup" or an object such as {serviceName: "login", error: E9000100}
// (a session not bound to the requested site); both are auth stubs, never data.
const AUTH_ERROR_MARKERS = [/"actionRequired"\s*:/, /SME\s*-\s*קלט לא תקין/];

/**
 * Guarded writer. `dump(page, fname, urlPath, postBody)` fetches one gateway endpoint inside
 * the page with the app's custom headers, rejects login-shell HTML / non-JSON / auth-error
 * stubs (file not written, previous one kept, run marked failed), otherwise writes pretty JSON
 * atomically and returns the parsed body. `state.account` is sent as the `accountnumber`
 * header and is set by the caller once known; `state.failed` is read by runScrape for the exit code.
 */
export function createDumper(outDir, { account = '', site = 'retail', businessprocessid = 'MY_ACCOUNT_HOMEPAGE' } = {}) {
  const state = { account, failed: false };
  fs.mkdirSync(outDir, { recursive: true });

  async function dump(page, fname, urlPath, postBody) {
    const res = await page.evaluate(async (urlPath, postBody, account, site, bpid) => {
      const headers = {
        accept: 'application/json, text/plain, */*',
        language: 'HEBREW',
        site,
        accountnumber: account,
        businessprocessid: bpid,
      };
      const init = { credentials: 'include', headers };
      if (postBody) {
        init.method = 'POST';
        init.headers = { ...headers, 'content-type': 'application/json' };
        init.body = JSON.stringify(postBody);
      }
      const r = await fetch(urlPath, init);
      return { status: r.status, body: await r.text() };
    }, urlPath, postBody ?? null, state.account, site, businessprocessid);

    const { status, body } = res;
    const size = String(body.length).padStart(9);
    const reject = (why) => {
      console.log(`  --  ${size}B  ${fname}  <-- ${why}, NOT WRITTEN (previous file kept)`);
      state.failed = true;
      return null;
    };
    if (/^\s*<(!doctype|html)/i.test(body)) return reject('LOGIN-SHELL HTML');
    let parsed;
    try { parsed = JSON.parse(body); } catch { return reject('NOT JSON'); }
    if (AUTH_ERROR_MARKERS.some((re) => re.test(JSON.stringify(parsed)))) return reject('AUTH-ERROR STUB');

    const target = path.join(outDir, fname);
    fs.writeFileSync(`${target}.tmp`, JSON.stringify(parsed, null, 2), 'utf8');
    fs.renameSync(`${target}.tmp`, target);
    console.log(`  ${status}  ${size}B  ${fname}${status !== 200 ? '  <-- non-200' : ''}`);
    return parsed;
  }
  return { dump, state };
}

/**
 * Browser lifecycle: launch headless, log in, run `body(page)`, always close the browser, then
 * exit 0 / the Exit code / 1 when `state.failed`. `body` throws Exit for fatal conditions.
 */
export async function runScrape(state, body, { loginPage } = {}) {
  const browser = await puppeteer.launch({ headless: true });
  let code = 0;
  try {
    const page = await browser.newPage();
    await page.setCacheEnabled(false);
    await page.setViewport({ width: 1024, height: 768 });
    await login(page, loginPage);
    await body(page);
  } catch (e) {
    if (!(e instanceof Exit)) throw e;
    console.error(e.message);
    code = e.code;
  } finally {
    await browser.close();
  }
  console.log('----------------------------------------');
  process.exit(code || (state.failed ? 1 : 0));
}
