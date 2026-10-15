---
name: analyst-refresh
description: Refresh the raw Analyst (אנליסט, amitim.analyst.co.il) savings data in data/analyst/raw/ — the household's old self-employed קופת גמל balance — by calling the logged-in customer portal's API over CDP. Activate when the user asks to refresh, re-scrape, or pull fresh Analyst / אנליסט / amitim / קופת גמל data.
---

# Analyst (אנליסט) Raw Data Refresh

Long-term **savings** source (like Harel and More): `normalize.py` emits
`savings` only, never `transactions`. Holds one self-employed קופת גמל
(kupa 5036, "אנליסט מסלולית"), liquid in 2057.

## Port / profile

Registry port **9229**, profile `~/.chrome-cdp-analyst`.

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9229 --user-data-dir="$HOME/.chrome-cdp-analyst" \
  --no-first-run --no-default-browser-check --new-window \
  "https://amitim.analyst.co.il/lobby" >/tmp/chrome-cdp-analyst.log 2>&1 &
for i in $(seq 1 10); do sleep 2; curl -s http://127.0.0.1:9229/json/version | grep -q Browser && break; done
```

**The USER logs in** (ID + SMS OTP, behind reCAPTCHA). Never type credentials.
Logged in = tab on `https://amitim.analyst.co.il/lobby`, title `אנליסט - מבט כללי`.

## Run

```bash
.claude/skills/analyst-refresh/scripts/dump.sh [PORT]   # default 9229
python3 data/analyst/normalize.py
```

`dump.sh` takes the port as its first arg and only touches the tab whose URL
starts with `https://amitim.analyst.co.il/`, so it works from any Chrome the
user happens to be logged into (e.g. `dump.sh 9226`).

## Endpoints

Base: `https://amitim.analyst.co.il/AnalystCustomersApiFront/api/`

| File | Call | Contents |
|---|---|---|
| `sum-financial-data.json` | `POST Accounts/GetCustomerSumFinancialData` body `{}` | `data.sumFinancialData.products[]` (per kupa type) → `accounts[]`: `sumAccount`, `kupaNum`, `accountMainForShow`, `nezilutDate` (liquidity, dd/mm/yyyy), `isNazil`, `state` (עצמאי/שכיר), `revaluationDate` |

Seen at login but not scraped: `Savers/GetMainPersonalDetails` (PII, not needed),
`Authorization/IsExistPrivacyPolicy`, `Configuration/GetConfiguration`.

## Gotchas

- **POST only** — `GET` returns 405 with an empty body.
- **Cookie-only auth** (HttpOnly; `sessionStorage.auth` is `{}`), so an in-tab
  `fetch(..., {credentials:'include'})` is enough — no bearer header to copy.
- **Double-encoded body**: the response is a JSON string whose content is JSON.
  `dump.sh` unwraps until it gets an object.
- **Stub guard**: `dump.sh` refuses to write unless HTTP 200, `isError:false`
  and `products` is an array; it exits 2 and keeps the previous file otherwise.
- Raw CDP (Node 22 `WebSocket`) rather than playwright-cli, same reason as
  more-refresh: playwright attach has hung on these multi-tab Chromes.
- Balances revalue monthly (`revaluationDate` = last day of prior month).
