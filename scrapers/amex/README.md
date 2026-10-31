# AMEX scraper

`scrape.mjs` logs in to American Express Israel (Isracard/ICC) headless with `puppeteer` and
writes the same raw files as `.claude/skills/refresh/scripts/amex/dump.sh` to `data/amex/raw/`,
so `data/amex/normalize.py` and `data/validate.py dump amex` work unchanged. No Chrome/CDP
session needed.

## Login

It fills and submits the site's own permanent-password form on
`https://he.americanexpress.co.il/personalarea/login/` (`#flip` to the password face, then
`#otpLoginId_ID`, `#cardnum`, `#otpLoginPwd`). It does not build the login requests itself the
way `israeli-bank-scrapers` does (`ValidateIdData` -> `performLogonI`, now outdated). The live
form sends `ValidateIdDataNoReg` -> `IsRegisterNoReg` -> `performLogonA` to
`/services/ProxyRequestHandler.ashx` with the page's `__RequestVerificationToken`. Once the
server answers `isCaptcha: "true"` it also adds a reCAPTCHA v3 token, which only the page can
produce. The scraper only reads those responses to classify the result:

| Signal | Result |
|---|---|
| page lands on `web.americanexpress.co.il` after `performLogon*` (or `status: "1"`) | logged in |
| `ValidateIdDataNoReg` returnCode `4` / `49`, `performLogon*` status `3`, `/RenewPassword` | exit 3 `CHANGE_PASSWORD` |
| returnCode `5`, status `2` + returnCode `665`, `/connectionIssue` | exit 3 `ACCOUNT_BLOCKED` |
| any other returnCode / status, `IsRegisterNoReg` returnCode `7` | exit 3 `INVALID_PASSWORD` |
| `#otpInput` visible, or a reCAPTCHA challenge (`bframe`) | exit 3 `OTP_REQUIRED` |
| anything else after 60 s | exit 1; `login-unknown.{png,txt}` saved to the out dir |

## Data

1. Navigate to `https://web.americanexpress.co.il/transactions` and capture the SPA's own
   `/ocp/transactions/DigitalV3.Transactions/<Method>` POSTs:
   `GetCardList` -> `cardList.json` (required), `GetTransactionsList` -> `transactionsList.json`,
   `InitContent` -> `initContent.json`, `GetPersonalComponents` -> `personalComponents.json`,
   `GetCampaign` -> `campaign.json`. A method that is not captured keeps its previous file.
2. For every `isActive` card in `cardList.json`, for the current and previous billing month
   (`--months N` for more), POST `GetTransactionsList` with dump.sh's body
   (`card4Number`, `isNextBillingDate: true`, `cardStatus: 0`, `billingMonth: "01/MM/YYYY"`,
   `companyCode`, `isPartner`) -> `transactions_<suffix>_<MM-YYYY>.json`. The request reuses
   the SPA's own `GetTransactionsList` headers. It is sent from inside the page first; if that
   returns login-shell HTML, it is re-sent from Node with the context's cookie jar (the
   equivalent of dump.sh's `page.request.post`).

Stub guard (as in dump.sh): login-shell HTML, non-JSON and non-200 responses are not written
(the previous file is kept) and fail the run. Writes are atomic (tmp + rename).
`errorCode: "22"` / `isSuccess: false` on a per-card file is benign: that card had no activity
that month. If `GetCardList` is not captured, the scraper checks `GET /IsLoggedIn`: live means
the SPA route moved, not that the session expired. `capture-unknown.*` is saved.

## Env (repo-root `.env`)

`AMEX_ID` (teudat zehut), `AMEX_CARD6_DIGITS` (last 6 digits of the card), `AMEX_PASSWORD`.
A missing one is reported by name, never by value.

## Run

    cd scrapers/amex && npm install   # first time
    node scrapers/amex/scrape.mjs [--out DIR] [--months N]   # from repo root; defaults data/amex/raw, 2

## Browser (Cloudflare, #64)

Cloudflare blocks a Chrome that puppeteer launches itself: headed gets "Sorry, you have been blocked"
on the plain GET, headless loads the form but gets a 403 on `ValidateIdDataNoReg` (checked 2026-10-31).
A plain Chrome the scraper spawns itself (fresh temp profile, `--remote-debugging-port`, no
`--enable-automation`) and attaches to over CDP loads the form. So the scraper does that, headed: it needs a
display (the launchd worker runs in the GUI session) and a window opens for the run. `AMEX_CHROME`
overrides the binary; `AMEX_HEADLESS=1` restores puppeteer's headless launch. No stealth patches.

## Exit codes

- 0 ok
- 1 failure (unknown login outcome / timeout, a file rejected, cardList or every per-card pull missing); retryable
- 2 missing env var or bad args
- 3 `LOGIN FAILED: INVALID_PASSWORD | CHANGE_PASSWORD | OTP_REQUIRED | ACCOUNT_BLOCKED | BOT_BLOCKED`; needs a human, do not retry.
  `BOT_BLOCKED` = a login call got HTTP 403/429 (the site's bot protection; no credential was judged). The refusal's
  status, `server` header and first 300 body chars are saved to `login-blocked.{png,txt}` (response only, never the request).
