# Max scraper

`scrape.mjs` logs in to Max (ex-Leumi Card) headless with `puppeteer` (same flow as
`israeli-bank-scrapers`' Max scraper: personal-area popup → password tab → `#user-name` /
`#password`), then calls `onlinelcapi.max.co.il` from inside the page and writes to
`data/max/raw/`:

- `categories.json` — `/api/contents/getCategories`
- `transactions_YYYY-MM.json` — `/api/registered/transactionDetails/getTransactionsAndGraphs`
  (month view, all users/cards) for the last `--months` months plus next month

Stub guard: login-shell HTML, non-JSON and non-200 responses are not written (previous file
kept) and fail the run. At least one month must be written. No Chrome/CDP session needed.

## Env (repo-root `.env`)

`MAX_USERNAME`, `MAX_PASSWORD` (the max.co.il username + password, not the ID/SMS login).
A missing one is reported by name (never value).

## Run

    cd scrapers/max && npm install   # first time
    node scrapers/max/scrape.mjs [--out DIR] [--months N]   # from repo root; defaults data/max/raw, 6

## Exit codes

- 0 ok
- 1 failure (unknown login outcome / timeout, a file rejected, no month written); retryable
- 2 missing env var or bad args
- 3 `LOGIN FAILED: INVALID_PASSWORD` or `CHANGE_PASSWORD`; needs a human, do not retry
