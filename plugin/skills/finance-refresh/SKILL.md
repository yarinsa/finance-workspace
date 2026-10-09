---
name: finance-refresh
description: Refresh raw financial data by re-scraping a source (bank, credit card, or aggregator) over CDP with the user logging in manually. Activate when the user asks to refresh, re-scrape, update, or pull fresh data for their accounts, banks, cards, or a named source (cal, amex, discount, leumi, harel, riseup).
---

# Finance refresh — dispatcher

Routes a refresh request to the right per-source refresh skill. Each source drives a
logged-in Chrome over CDP via `playwright-cli` and dumps authenticated API responses
into `<data_dir>/<source>/raw/`.

## Sources

| Ask for… | Skill | Captures |
|---|---|---|
| CAL credit cards | `cal-refresh` | card transactions + billings |
| American Express / Isracard | `amex-refresh` | card transactions + billings |
| Discount checking (personal) | `discount-account-refresh` | balance, tx, cards, deposits |
| Discount business (SME) | `discount-business-refresh` | business account + loans |
| Discount mortgage + loans | `discount-mortgage-refresh` | mortgage/loan amortization |
| Leumi checking + loans | `leumi-account-refresh` | balance, tx, loan schedules |
| Harel pension / study funds | `harel-refresh` | long-term savings balances |
| RiseUp aggregator | `riseup-raw-refresh` | budget envelopes, balances |

## Rules (do not break)

1. **Never auto-type credentials.** Launch Chrome, then wait for the user to log in
   in the visible window. Confirm they're logged in before scraping.
2. **One source at a time** — each has its own login. If the user wants "everything",
   walk through them sequentially with a pause for each login.
3. Refreshing is the **confirm-first** tier — it opens a browser and hits live APIs.
4. After a successful dump, offer `/finance-digest` to rebuild the digested outputs
   (raw data alone doesn't update answers until digested).

## Flow

1. Determine the source from the user's request (map to the table above).
2. Activate that source's `<source>-refresh` skill and follow its documented steps
   (CDP port, login wait, `scripts/dump.sh`, gotchas).
3. Confirm the raw files updated under `<data_dir>/<source>/raw/`.
4. Offer to digest.
