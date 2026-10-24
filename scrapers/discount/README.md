# Discount scrapers

`lib.mjs` holds the shared foundation (login, guarded atomic writer, `Exit`, env check, browser
lifecycle). `scrape.mjs` does checking; `scrape-mortgage.mjs` does mortgage + loans (below).

Deterministic scrape of Bank Discount personal checking. It does its own login with
`puppeteer` (headless; same flow as `israeli-bank-scrapers`' Discount scraper, which is no
longer a dependency), then calls the telebank gateway API from inside the page and writes
the same raw files `.claude/skills/discount-account-refresh/scripts/dump.sh` writes
(`userAccountsData`, `infoAndBalance`, `headerData`, `dashboardBalances`, `creditLine`,
`transactions`, `categoriesList`, `totalCreditAndDebitByMonth`, `creditCards_*`,
`deposits_depositsDetails`; pretty JSON, atomic tmp + rename). It replaces `dump.sh` for
checking; no Chrome/CDP session needed. `fetch-transactions_scraper.json` is no longer written.

Stub guard (as in dump.sh): login-shell HTML, non-JSON and auth-error stubs are not written
(previous file kept) and fail the run. `infoAndBalance.json` and `transactions.json` are required.
The account number is `DefaultAccountNumber` from `userAccountsData` (fallback `--account`).

## Env (repo-root `.env`)

`DISCOUNT_ID`, `DISCOUNT_PASSWORD`, `DISCOUNT_NUM`. A missing one is reported by name (never value).

## Run

    cd scrapers/discount && npm install   # first time
    node scrapers/discount/scrape.mjs [--out DIR] [--account N] [--num-tx N]   # from repo root
    # defaults: --out data/discount/raw, --num-tx 500

## Exit codes

- 0 ok
- 1 failure (unknown login outcome / timeout, a file rejected or missing, required file missing); retryable
- 2 missing env var or bad args
- 3 `LOGIN FAILED: INVALID_PASSWORD` or `CHANGE_PASSWORD`; needs a human, do not retry

## Mortgage (`scrape-mortgage.mjs`)

Same login, headers (`site: retail`, `businessprocessid: MY_ACCOUNT_HOMEPAGE`) and stub guard;
replaces `.claude/skills/discount-mortgage-refresh/scripts/dump.sh`. Writes `accountsList.json`,
`onlineLoans_loansQuery.json` and `mortgage_details.json` (required) to `data/discount-mortgage/raw`.
The `mortgage/details` POST body is built from `accountsList` (`OldAccountInfo` per entry).

    node scrapers/discount/scrape-mortgage.mjs [--out DIR] [--account N]

## Business (`scrape-business.mjs`)

Replaces `.claude/skills/discount-business-refresh/scripts/dump.sh` and writes the same files to
`data/discount-business/raw` (`infoAndBalance.json` and `transactions.json` required). Two
differences from personal: it logs in through `LOGIN_PAGE_SME` (ID + password, no `#aidnum`;
`login(page, 'LOGIN_PAGE_SME')` lands on `/apollo/business2/`), because a personal session that
opens business2 is logged out by the server; and every call sends `site: sme`.
The account defaults to dump.sh's `0216859524` (`--account` overrides).

The bank answers "nothing here" as `{"Error": ...}` JSON (no credit line, loans, deposits or
guarantees); those are written as-is, as dump.sh did. Any `actionRequired` body (`stepup`, or
`{serviceName: "login", E9000100}` from a session not bound to the site) is an auth stub and
is never written.

    node scrapers/discount/scrape-business.mjs [--out DIR] [--account N] [--num-tx N]
