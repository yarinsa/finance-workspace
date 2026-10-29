#!/usr/bin/env node
// Deterministic Discount personal-checking scrape: logs in itself (puppeteer, same flow as
// israeli-bank-scrapers' Discount scraper; shared foundation in lib.mjs) and writes the same raw
// files as .claude/skills/discount-account-refresh/scripts/dump.sh. Credentials come from <repo>/.env only.
import path from 'node:path';
import { repo, opt, requireLoginEnv, createDumper, runScrape, Exit, GATEWAY } from './lib.mjs';
import { dataDir } from '../tenant.mjs';

const outDir = path.resolve(opt('--out', dataDir(repo, 'discount/raw')));
const cliAccount = opt('--account', '');
const numTx = opt('--num-tx', '500');
if (!/^\d+$/.test(numTx) || Number(numTx) <= 0) {
  console.error('--num-tx must be a positive integer');
  process.exit(2);
}
requireLoginEnv();

const { dump, state } = createDumper(outDir, { account: cliAccount });

await runScrape(state, async (page) => {
  const B = GATEWAY;
  const first = await dump(page, 'userAccountsData.json', `${B}/userAccountsData?FetchAccountsNickName=true&FirstTimeEntry=true`);
  const account = first?.UserAccountsData?.DefaultAccountNumber || cliAccount;
  state.account = account;
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
    state.failed = true;
  }
});
