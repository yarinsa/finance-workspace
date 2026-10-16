# Discount scraper

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
