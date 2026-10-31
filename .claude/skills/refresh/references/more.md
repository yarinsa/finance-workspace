
# More (מור) Raw Data Refresh

Long-term **savings** source (like Harel): normalize.py emits `savings` only,
never `transactions`.

## Port / profile

Registry port **9228**, profile `~/.chrome-cdp-more`. The first scrape (2026-10)
was done from the **AMEX Chrome on 9226**, where the user happened to be logged
in — `dump.sh` takes the port as its first arg, so either works:
`dump.sh 9226`. It only touches the tab whose URL starts with
`https://my-account.more.co.il/personalarea`; other tabs in that window are ignored.

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9228 --user-data-dir="$HOME/.chrome-cdp-more" \
  --no-first-run --no-default-browser-check --new-window \
  "https://my-account.more.co.il/personalarea/dashboard" >/tmp/chrome-cdp-more.log 2>&1 &
for i in $(seq 1 10); do sleep 2; curl -s http://127.0.0.1:9228/json/version | grep -q Browser && break; done
```

**The USER logs in** (ID + OTP). Never type credentials.

## Run

```bash
.claude/skills/refresh/scripts/more/dump.sh [PORT]   # default 9228
poetry run python data/more/normalize.py
```

## How the data is obtained (and why not a fetch)

| Data | Backing endpoint | How we read it |
|---|---|---|
| balances per fund (kupaNum, balanceData, liquidityDate, employer, workState) | `POST /paapi/accounts/getDashboardAccountsData` body `{kupaNums:[...]}`, Bearer `AUTH-TOKEN` | `sessionStorage.accountData` |

- The SPA calls `getDashboardAccountsData` **once at login** and caches it in
  `sessionStorage.accountData` (`[own, managed-for-others]`). A reload does NOT
  refire it — network capture after reload only shows CMS `/api/content/*`.
  Reading the SPA's own cache needs no request, so nothing can be mutated.
- Balances update monthly (by the 12th, as of last business day of prior month);
  `lastUpdate` gives the as-of date.
- Other read endpoints seen in the bundle (all POST, not scraped yet):
  `accounts/getKupaDetails {kupaNum}`, `getKupaTransactions`, `getMaslulYield`,
  `getKupaInvestPortfolio` — the place for fees/yield later.
- Raw CDP (Node 22 `WebSocket`) is used instead of playwright-cli:
  `playwright-cli attach` hung on the shared 9226 Chrome and `connectOverCDP`
  did not enumerate the more.co.il tab.
- Session is dead when `accountData` is missing → dump.sh exits 2 and keeps the
  previous file. AUTH-TOKEN lives ~10 min (`AUTH-TOKEN-EXP`) but the cached
  accountData stays in the tab.
