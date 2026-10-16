#!/usr/bin/env node
// Deterministic Discount personal-checking scrape: logs in itself (puppeteer, same flow as
// israeli-bank-scrapers' Discount scraper) and writes the same raw files as
// .claude/skills/discount-account-refresh/scripts/dump.sh. Credentials come from <repo>/.env only.
import puppeteer from 'puppeteer';
import dotenv from 'dotenv';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '../..');
dotenv.config({ path: path.join(repo, '.env'), quiet: true });

const args = process.argv.slice(2);
const opt = (name, def) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : def;
};
const outDir = path.resolve(opt('--out', path.join(repo, 'data/discount/raw')));
const cliAccount = opt('--account', '');
const numTx = opt('--num-tx', '500');
if (!/^\d+$/.test(numTx) || Number(numTx) <= 0) {
  console.error('--num-tx must be a positive integer');
  process.exit(2);
}

const missing = ['DISCOUNT_ID', 'DISCOUNT_PASSWORD', 'DISCOUNT_NUM'].filter((k) => !process.env[k]);
if (missing.length) {
  console.error(`Missing env: ${missing.join(', ')}`);
  process.exit(2);
}

const BASE_URL = 'https://start.telebank.co.il';
// Thrown instead of process.exit() inside the browser session, so `finally` closes Chrome.
class Exit extends Error { constructor(code, msg) { super(msg); this.code = code; } }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Same as the library's fillInput: clear, then type.
async function fillInput(page, selector, value) {
  await page.$eval(selector, (el) => { el.value = ''; });
  await page.type(selector, value);
}

function classifyUrl(url) {
  const u = url.toLowerCase();
  if (/^https:\/\/start\.telebank\.co\.il\/apollo\/retail\d*\/(#\/my_account_homepage)?$/.test(u)) return 'SUCCESS';
  if (u === `${BASE_URL}/apollo/core/templates/lobby/masterpage.html#/login_page`) return 'INVALID_PASSWORD';
  if (u === `${BASE_URL}/apollo/core/templates/lobby/masterpage.html#/pwd_renew`) return 'CHANGE_PASSWORD';
  return 'UNKNOWN';
}

/** Log in; returns on success, otherwise throws Exit with the right code. */
async function login(page) {
  await page.goto(`${BASE_URL}/login/#/LOGIN_PAGE`, { waitUntil: 'load' });
  await page.waitForSelector('#tzId');
  await fillInput(page, '#tzId', process.env.DISCOUNT_ID);
  await fillInput(page, '#tzPassword', process.env.DISCOUNT_PASSWORD);
  await fillInput(page, '#aidnum', process.env.DISCOUNT_NUM);
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

const AUTH_ERROR_MARKERS = [/actionRequired["\s:]*["\s]*stepup/i, /SME\s*-\s*קלט לא תקין/];
let failed = false;
let account = cliAccount;

/** Fetch one endpoint inside the page, apply the stub guard, write the file atomically. */
async function dump(page, fname, urlPath, postBody) {
  const res = await page.evaluate(async (urlPath, postBody, account) => {
    const headers = {
      accept: 'application/json, text/plain, */*',
      language: 'HEBREW',
      site: 'retail',
      accountnumber: account,
      businessprocessid: 'MY_ACCOUNT_HOMEPAGE',
    };
    const init = { credentials: 'include', headers };
    if (postBody) {
      init.method = 'POST';
      init.headers = { ...headers, 'content-type': 'application/json' };
      init.body = JSON.stringify(postBody);
    }
    const r = await fetch(urlPath, init);
    return { status: r.status, body: await r.text() };
  }, urlPath, postBody ?? null, account);

  const { status, body } = res;
  const size = String(body.length).padStart(9);
  const reject = (why) => {
    console.log(`  --  ${size}B  ${fname}  <-- ${why}, NOT WRITTEN (previous file kept)`);
    failed = true;
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

fs.mkdirSync(outDir, { recursive: true });
const browser = await puppeteer.launch({ headless: true });
let code = 0;
try {
  const page = await browser.newPage();
  await page.setCacheEnabled(false);
  await page.setViewport({ width: 1024, height: 768 });
  await login(page);

  const B = '/Titan/gatewayAPI';
  const first = await dump(page, 'userAccountsData.json', `${B}/userAccountsData?FetchAccountsNickName=true&FirstTimeEntry=true`);
  account = first?.UserAccountsData?.DefaultAccountNumber || cliAccount;
  if (!account) {
    throw new Exit(1, 'No account number: userAccountsData had no DefaultAccountNumber and --account not given');
  }
  console.log(`Account : ${account}`);
  console.log('----------------------------------------');

  const info = await dump(page, 'infoAndBalance.json', `${B}/accountDetails/infoAndBalance/${account}`);
  await dump(page, 'headerData.json', `${B}/accountDetails/headerData/${account}`);
  await dump(page, 'dashboardBalances.json', `${B}/dashboard/dashboardBalances`, { AccountNumber: account });
  await dump(page, 'creditLine.json', `${B}/account/creditLine`, { AccountNumber: account, SubService: 'CurrentAccountLastTransaction' });
  const txns = await dump(page, 'transactions.json',
    `${B}/lastTransactions/transactions/${account}/forHomePage?NumberOfTransactions=${numTx}&IsTransactionDetails=True&IsFutureTransactionFlag=True&IsEventNames=True&IsCategoryDescCode=True`);
  await dump(page, 'categoriesList.json', `${B}/lastTransactions/categoriesList`);
  await dump(page, 'totalCreditAndDebitByMonth.json', `${B}/lastTransactions/totalCreditAndDebitByMonth/${account}/3`);
  await dump(page, 'creditCards_totalDebitTransactions.json', `${B}/creditCards/totalDebitTransactions/${account}`);
  await dump(page, 'creditCards_pastOrFutureDebitTotal.json', `${B}/creditCards/cardsPastOrFutureDebitTotal/${account}/F`);
  await dump(page, 'creditCards_cardListForActivation.json', `${B}/creditCards/cardListForActivation/${account}`);
  await dump(page, 'deposits_depositsDetails.json', `${B}/deposits/depositsDetails/${account}/1`);

  if (!info || !txns) {
    console.error('infoAndBalance.json and transactions.json are both required');
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
