# CAL scraper

`scrape.mjs` logs in to cal-online headless (puppeteer; same flow as israeli-bank-scrapers'
visaCal scraper) with `CAL_USERNAME` / `CAL_PASSWORD` from the repo-root `.env`, then calls the
same `api.cal-online.co.il` endpoints as `.claude/skills/cal-refresh/scripts/dump.sh` and writes
the same files to `data/cal/raw` (pretty JSON, atomic, stub guard). The `CALAuthScheme` token is
read from `sessionStorage["auth-module"]` after login; card/account ids come from `account/init`.
`monthlyDebitsSummary.json` and `filteredTransactions.json` are required.

    cd scrapers/cal && npm install          # first time
    node scrapers/cal/scrape.mjs [--out DIR]  # from repo root

Exit codes: 0 ok · 1 failure (retryable) · 2 missing env · 3 `LOGIN FAILED: INVALID_PASSWORD |
CHANGE_PASSWORD | OTP_REQUIRED` (needs a human; the sync reports needs_login and never retries).
