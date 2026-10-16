# Leumi scraper

`scrape.mjs` logs in to hb2.bankleumi.co.il headless (puppeteer; same flow as israeli-bank-scrapers'
Leumi scraper) with `LEUMI_USERNAME` / `LEUMI_PASSWORD` from the repo-root `.env`, then makes the
calls of `.claude/skills/leumi-account-refresh/scripts/dump.sh` (`accounts.json`, `summary.json`,
`transactions.json`, all required; the Broker `SessionID` is read from localStorage) and
`dump-loans.sh` (`loans.json`, `loan-summary.html`, `loan-activity-<N>.html`) into `data/leumi/raw`
(pretty JSON, atomic, stub guard; `loans.json` is not written when a loan comes back without its number).

    cd scrapers/leumi && npm install          # first time
    node scrapers/leumi/scrape.mjs [--out DIR] [--account-index 1] [--num-tx 500] [--loans "3 4"]

Exit codes: 0 ok · 1 failure (retryable) · 2 missing env / bad args · 3 `LOGIN FAILED:
INVALID_PASSWORD | CHANGE_PASSWORD | ACCOUNT_BLOCKED | OTP_REQUIRED` (needs a human; the sync
reports needs_login and never retries).
