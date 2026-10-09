---
name: riseup-raw-refresh
description: Refresh the raw RiseUp API data dump in data/riseup/raw/ by driving a logged-in Chrome via CDP and scraping the authenticated cashflow/budget/balance endpoints. Activate when the user asks to refresh, re-scrape, update, or pull fresh RiseUp raw data.
---

# RiseUp Raw Data Refresh

Pulls **raw** RiseUp API responses straight from the logged-in web app and dumps
them as JSON files into `data/riseup/raw/`, for later digestion/analysis.

This is different from the `riseup` skill (which uses `riseup-cli`). This skill
scrapes the live authenticated endpoints directly through the browser, so it
captures the exact API payloads with no intermediate tool.

## Output layout

```
data/
  riseup/
    raw/            <- one JSON file per API endpoint (this skill writes here)
```

The `data/<source>/raw` layout is intentional so other sources can be added
later (e.g. `data/bank/raw`).

## How it works (the flow we use)

1. **Launch Chrome with a CDP debug port** and a dedicated profile (so login
   persists between runs and we don't touch the user's main Chrome profile):

   ```bash
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
     --remote-debugging-port=9222 \
     --user-data-dir="$HOME/.chrome-cdp-riseup" \
     "https://input.riseup.co.il/login?redirectTo=sr" \
     >/tmp/chrome-cdp.log 2>&1 &
   ```

   Verify it's up: `curl -s http://localhost:9222/json/version`

   > The Claude-in-Chrome extension and a plain `playwright-cli open` window may
   > not be visible to the user in some setups — CDP attach to a real Chrome is
   > the reliable headed path.

2. **Attach playwright-cli to it:**

   ```bash
   playwright-cli -s=riseup attach --cdp=http://localhost:9222
   ```

   If Chrome opened a "set up sync" intro on a fresh profile, select tab 0 and
   navigate it to the login page:

   ```bash
   playwright-cli -s=riseup tab-select 0
   playwright-cli -s=riseup goto "https://input.riseup.co.il/login?redirectTo=sr"
   ```

3. **The USER logs in** in the visible Chrome window (phone + SMS OTP).
   **Never enter credentials or OTP codes yourself.** Wait for the user to say
   they're done. Confirm with:

   ```bash
   playwright-cli -s=riseup --raw eval "location.href"
   # expect https://input.riseup.co.il/web/home/current
   ```

4. **Run the dump script:**

   ```bash
   .claude/skills/riseup-raw-refresh/scripts/dump.sh
   # or: dump.sh <session> <out_dir>
   ```

   It fetches each endpoint from the logged-in page context (cookies included)
   and writes pretty-printed JSON, one file per endpoint.

## Endpoints captured

The cashflow / budget / balance set (see `scripts/dump.sh` `EPS=(...)` to edit):

| File | Endpoint | Notes |
|------|----------|-------|
| `budget_<YYYY-MM>_6.json` | `/api/budget/<month>/6` | **Main cashflow for the current month** (large) |
| `budget_current.json` | `/api/budget/current` | Current budget summary |
| `budget_oldest.json` | `/api/budget/oldest` | Earliest available budget month |
| `current-balance.json` | `/api/current-balance` | Bank account balances |
| `current-credit-card-debt.json` | `/api/current-credit-card-debt` | CC debt |
| `cashflow-start-day.json` | `/api/cashflow-start-day` | Day the cashflow month starts |
| `insights_all.json` | `/api/insights/all` | Insights |
| `application-state.json` | `/api/application-state` | App state |
| `credentials-info.json` | `/api/credentials-info` | Linked credentials metadata |
| `creds-to-accounts.json` | `/api/creds-to-accounts` | Credential → account mapping |
| `subscription-state-simplified.json` | `/api/subscription-state-simplified` | RiseUp subscription |
| `consolidated_customer-state.json` | `/api/consolidated/customer-state` | Customer state |
| `cashflow-models_churn_data.json` | `/api/cashflow-models/churn/data` | Churn model data |
| `plans.json` | `/api/plans` | Plans (may be `[]`) |

To discover more endpoints: after login, reload `/web/home/current` and run
`playwright-cli -s=riseup requests | grep 'input.riseup.co.il/api'`
(filter out `no-auth`, `feature-flag`, `segment`).

## Gotchas (learned the hard way)

- **`run-code --raw` output is double-JSON-encoded.** The returned value is a
  string that must be `JSON.parse`d **twice** to reach `{status, body}`, and
  `body` is itself a JSON string. `dump.sh` handles this. Parsing only once
  yields `undefined` bodies.
- **Never iterate a big response with `Object.entries` assuming object keys** —
  if it's an array/string you'll spray millions of index-named files and fill
  the disk. `dump.sh` uses a fixed named endpoint list instead.
- `budget/<month>/6` is multi-MB; that's expected.
- Some endpoints legitimately return `[]` / `{}` (e.g. `plans`) — not an error.

## Cleanup

Stop the browser session when finished (the Chrome stays running so login
persists for next time — detach rather than close):

```bash
playwright-cli -s=riseup detach
```
