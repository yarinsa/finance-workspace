# Harel scraper

`scrape.mjs` scrapes Harel (pension + study funds) **headless, without logging in**. Harel's only
login is ID + phone + a one-time code (SMS/email), which is never automated; the human logs in once
in the Chrome profile `~/.chrome-cdp-harel` (port 9227, see the `harel-refresh` skill) and this
reuses that session:

- Chrome on 9227 is up → `puppeteer.connect` and work in a new tab of it (the profile is locked).
- Otherwise → launch `/Applications/Google Chrome.app` headless on the profile. It must be the same
  binary: the profile's cookies are encrypted with Google Chrome's Keychain key.

It loads `client-view.aspx`, takes the per-page-load `ticket` from the page's first API request,
and writes `online-data.json`, `customer-products.json`, `client-claims-by-area.json`,
`client-requests.json` to `data/harel/raw/` (atomic; HTML / non-JSON / non-200 is not written and
fails the run).

## Logging in from the app (`--login`)

`node scrapers/harel/scrape.mjs --login --otp-file PATH` logs in when the session lapsed: it types
`HAREL_ID` and `HAREL_PHONE` from `.env`, picks SMS, prints `OTP_REQUESTED`, and waits up to 8
minutes for the code to appear in `PATH` (read once, then deleted). The sync worker writes that file
from the code the human typed on `/syncs`. A rejected code exits 3 `OTP_REJECTED` and is never
resubmitted (that would send another SMS). On an unexpected page it saves
`$TMPDIR/harel-login-debug/page.{png,txt}`.

## Run

    cd scrapers/harel && npm install   # first time
    node scrapers/harel/scrape.mjs [--out DIR]   # from repo root
    node scrapers/harel/scrape.mjs --check       # VERDICT: LIVE | LOGGED_OUT, writes nothing

## Exit codes

- 0 ok / live
- 1 failure (no ticket, a file rejected, browser failed to start); retryable
- 3 `LOGIN FAILED: SESSION_EXPIRED` (log in in the Chrome window, then `sync/resume.py harel`, or from
  the app), `OTP_TIMEOUT`, `OTP_REJECTED`, `LOGIN_ERROR`: a human must act, never retried
- 2 bad args, or `--login` without `HAREL_ID` / `HAREL_PHONE` in `.env`

If Harel keeps its login only in session cookies, closing that Chrome logs you out; leaving the
window open keeps the CDP path working between syncs.
