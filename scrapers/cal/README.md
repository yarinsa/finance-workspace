# CAL scraper

`scrape.mjs` logs in to cal-online headless (puppeteer; same flow as israeli-bank-scrapers'
visaCal scraper) with `CAL_USERNAME` / `CAL_PASSWORD` from the repo-root `.env`, then calls the
same `api.cal-online.co.il` endpoints as `.claude/skills/refresh/scripts/cal/dump.sh` and writes
the same files to `data/cal/raw` (pretty JSON, atomic, stub guard). The `CALAuthScheme` token is
read from `sessionStorage["auth-module"]` after login; card/account ids come from `account/init`.
`monthlyDebitsSummary.json` and `filteredTransactions.json` are required.

Login flow (2026-10): `#ccLoginDesktopBtn` → iframe `connect.cal-online.co.il` (opens on the
ID + card-digits OTP tab, `/send-otp`) → `#regular-login` (`/regular-login`) → `userName` /
`password` → the form's single `button[type=submit]` ("כניסה"). Gotchas:

- **WAF**: a `HeadlessChrome` user agent gets HTTP 400 "Request Rejected" on www.cal-online.co.il,
  so the script swaps it for `Chrome` before navigating.
- **Clicks are in-page `element.click()`**: puppeteer's mouse click (and screenshots) hang when
  headless Chrome isn't painting frames (seen with the Mac's display asleep). Typing still works.
- An unrecognised post-submit state saves `login-unknown.png` (best-effort) + `login-unknown.txt`
  to the out dir; any CAL error banner is reported verbatim as exit 3.

    cd scrapers/cal && npm install          # first time
    node scrapers/cal/scrape.mjs [--out DIR]  # from repo root

Exit codes: 0 ok · 1 failure (retryable) · 2 missing env · 3 `LOGIN FAILED: INVALID_PASSWORD |
CHANGE_PASSWORD | OTP_REQUIRED` (needs a human; the sync reports needs_login and never retries).
