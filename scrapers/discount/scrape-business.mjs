#!/usr/bin/env node
// Deterministic Discount BUSINESS (SME) scrape: logs in itself (shared foundation in lib.mjs) and
// writes the same raw files as .claude/skills/discount-business-refresh/scripts/dump.sh to
// data/discount-business/raw. Credentials come from <repo>/.env only (same login as personal).
//
// Same backend as the personal scrapers; the differences are the `site: sme` header (with
// 'retail' every call is rejected with "SME - קלט לא תקין") and that the business2 app must be
// logged in through LOGIN_PAGE_SME (the personal session cannot open the SME app).
import path from 'node:path';
import { repo, opt, requireLoginEnv, createDumper, runScrape, Exit, GATEWAY } from './lib.mjs';

const DEFAULT_ACCOUNT = '0216859524'; // dump.sh's default business account
const outDir = path.resolve(opt('--out', path.join(repo, 'data/discount-business/raw')));
const account = opt('--account', DEFAULT_ACCOUNT);
const numTx = opt('--num-tx', '500');
if (!/^\d+$/.test(numTx)) {
  console.error('--num-tx must be a positive integer');
  process.exit(2);
}
requireLoginEnv();

const { dump, state } = createDumper(outDir, { account, site: 'sme' });

const ymd = (d) => d.toISOString().slice(0, 10).replaceAll('-', '');

await runScrape(state, async (page) => {
  console.log(`Account : ${account} (business)`);
  console.log('----------------------------------------');

  const B = GATEWAY;
  const A = account;
  const today = new Date();
  const farFuture = new Date(today);
  farFuture.setFullYear(today.getFullYear() + 20);

  // Balance & account info
  const info = await dump(page, 'infoAndBalance.json', `${B}/accountDetails/infoAndBalance/${A}`);
  await dump(page, 'dashboardBalances.json', `${B}/dashboard/dashboardBalances`, { AccountNumber: A });
  await dump(page, 'creditLine.json', `${B}/account/creditLine`, { AccountNumber: A, SubService: 'CurrentAccountLastTransaction' });
  await dump(page, 'liabilities.json', `${B}/balance/liabilities/${A}/Explicit`);

  // Transactions
  const tx = await dump(page, 'transactions.json',
    `${B}/lastTransactions/transactions/${A}/forHomePage?NumberOfTransactions=${numTx}&IsTransactionDetails=True&IsFutureTransactionFlag=True&IsEventNames=True&IsCategoryDescCode=True`);

  // Dashboard product balances
  await dump(page, 'dashboard_loansBalance.json', `${B}/dashboard/loansBalance/${A}`);
  await dump(page, 'dashboard_savingsBalance.json', `${B}/dashboard/savingsBalance/${A}`);
  await dump(page, 'dashboard_securitiesBalance.json', `${B}/dashboard/securitiesBalance/${A}`);
  await dump(page, 'dashboard_foreignAccountsBalance.json', `${B}/dashboard/foreignAccountsBalance/${A}`);

  // Loans, deposits
  await dump(page, 'onlineLoans_loansQuery.json', `${B}/onlineLoans/loansQuery/${A}`);
  await dump(page, 'deposits_depositsDetails.json', `${B}/deposits/depositsDetails/${A}/1`);

  // Credit cards
  await dump(page, 'creditCards_pastOrFutureDebitTotal_F.json', `${B}/creditCards/cardsPastOrFutureDebitTotal/${A}/F`);
  await dump(page, 'creditCards_pastOrFutureDebitTotal_P.json', `${B}/creditCards/cardsPastOrFutureDebitTotal/${A}/P`);
  await dump(page, 'creditCards_accountFutureDebitsTotal.json', `${B}/creditCards/accountFutureDebitsTotal/${A}`);
  await dump(page, 'creditCards_cardFutureCredits.json', `${B}/creditCards/cardFutureCredits/${A}/True`);
  await dump(page, 'creditCards_cardListForActivation.json', `${B}/creditCards/cardListForActivation/${A}`);

  // Business-specific
  await dump(page, 'guarantee_guaranteesInfo.json', `${B}/guarantee/guaranteesInfo`, {
    AccountNumber: A, GuaranteesTypeFilter: 0, BuildingNumFilter: '', ApartmentNumFilter: '',
    BeneficiaryNameFilter: '', GuaranteeIDNumFilter: '', BaseAmountFromFilter: '', BaseAmountToFilter: '',
    GuaranteeStatusCodeFilter: '',
    InfoParameters: {
      BalanceType: 4, RequestedMonth: '', RequestedQuarter: '', RequestedYear: '',
      EstablishmentFromDate: '', EstablishmentToDate: '', ValidityFromDate: '', ValidityToDate: '',
      ClosingFromDate: '', ClosingToDate: '',
    },
  });
  await dump(page, 'debitAuthorizations_list.json', `${B}/debitAuthorizations/list/${A}/NotRequired`);
  await dump(page, 'checks_draftChecksTotals.json', `${B}/checks/draftChecksTotals`,
    { AccountNumber: A, FromDate: ymd(today), ToDate: ymd(farFuture) });

  if (!info || !tx) throw new Exit(1, 'infoAndBalance.json and transactions.json are required');
}, { loginPage: 'LOGIN_PAGE_SME' });
