#!/usr/bin/env node
// Deterministic Discount mortgage + loans scrape: logs in itself (shared foundation in lib.mjs)
// and writes the same raw files as .claude/skills/discount-mortgage-refresh/scripts/dump.sh
// (accountsList, onlineLoans_loansQuery, mortgage_details). Credentials come from <repo>/.env only.
//
// Same headers as dump.sh: site 'retail', businessprocessid 'MY_ACCOUNT_HOMEPAGE'. The SME app's
// rebinding is what yields the `actionRequired: stepup` stub; a fresh headless login never
// visits it, and the stub guard still rejects it if it ever appears.
import path from 'node:path';
import { repo, opt, requireLoginEnv, createDumper, runScrape, Exit, GATEWAY } from './lib.mjs';

const outDir = path.resolve(opt('--out', path.join(repo, 'data/discount-mortgage/raw')));
const cliAccount = opt('--account', '');
requireLoginEnv();

const { dump, state } = createDumper(outDir, { account: cliAccount });

await runScrape(state, async (page) => {
  const B = GATEWAY;
  // Lookup only, not written: dump.sh takes the account as an argument (hardcoded default).
  // Here it is the bank's own DefaultAccountNumber, with --account as the override.
  const ua = await page.evaluate(async (B) => {
    const r = await fetch(`${B}/userAccountsData?FetchAccountsNickName=true&FirstTimeEntry=true`, {
      credentials: 'include',
      headers: {
        accept: 'application/json, text/plain, */*', language: 'HEBREW', site: 'retail',
        accountnumber: '', businessprocessid: 'MY_ACCOUNT_HOMEPAGE',
      },
    });
    try { return JSON.parse(await r.text()); } catch { return null; }
  }, B);
  const account = cliAccount || ua?.UserAccountsData?.DefaultAccountNumber;
  if (!account) {
    throw new Exit(1, 'No account number: userAccountsData had no DefaultAccountNumber and --account not given');
  }
  state.account = account;
  console.log(`Account : ${account}`);
  console.log('----------------------------------------');

  const accountsList = await dump(page, 'accountsList.json', `${B}/mortgage/accountsList/${account}`);
  await dump(page, 'onlineLoans_loansQuery.json', `${B}/onlineLoans/loansQuery/${account}`);

  // mortgage/details body is derived from accountsList: each AccountEntry.OldAccountInfo
  // becomes a MortgageAccountEntry (live ids, nothing hardcoded).
  let details = null;
  if (accountsList) {
    let entries = accountsList?.MortgageAccountsList?.AccountList?.AccountEntry ?? [];
    if (!Array.isArray(entries)) entries = [entries];
    const MortgageAccountEntry = entries.map((e) => {
      const o = e.OldAccountInfo || {};
      return { BankID: o.BankID, BranchID: o.BranchID, AccountType: o.AccountType, CurrencyID: o.CurrencyID, AccountID: o.AccountID };
    });
    details = await dump(page, 'mortgage_details.json', `${B}/mortgage/details`, { MortgageAccountBlock: { MortgageAccountEntry } });
  } else {
    console.error('accountsList.json missing: cannot build the mortgage/details body');
  }

  if (!details) {
    console.error('mortgage_details.json is required');
    state.failed = true;
  }
});
