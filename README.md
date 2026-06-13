# Finance Workspace

Personal finance management workspace. Data is pulled from Israeli banks and credit cards via the [israeli-bank-mcp](https://github.com/mottibec/israeli-bank-mcp) connector. Currency: ILS (₪).

## Structure

- `data/` — the scrape → normalize → digest pipeline (see below)
- `statements/` — raw bank/credit-card statements and CSV exports
- `receipts/` — receipts and invoices
- `reports/` — generated summaries and dashboards
- `budget.xlsx` — monthly budget vs. actual by category
- `net-worth.xlsx` — accounts, balances, and net worth over time

## Data pipeline

```
data/<source>/raw/  --(<source>/normalize.py)-->  data/<source>/normalized/  --(data/digest.py)-->  data/digested/snapshot.{json,md}
```

Each source has its own refresh skill that scrapes a logged-in Chrome via CDP into
`raw/`, plus a self-contained `normalize.py` that emits a common envelope
(`{source, entity, generated_at, records}`). `data/digest.py` runs every source's
normalizer, then combines all `normalized/*.json` into one consolidated snapshot.

Run `python3 data/digest.py` (or `--no-normalize` to combine existing output only).

| Source | Raw | normalize.py | Entities emitted |
|---|:--:|:--:|---|
| `discount` (personal checking) | ✅ | ✅ | accounts, transactions |
| `discount-business` (SME checking) | ✅ | ✅ | accounts, credit_cards, transactions |
| `discount-mortgage` (mortgage + loans) | ✅ | ✅ | loans |
| `leumi` (checking + loan total) | ✅ | ✅ | accounts, loans, transactions |
| `riseup` (aggregator) | ✅ | ✅ | accounts, credit_cards, income, subscription |

## Goals

1. **Budget & spending tracking** — categorize transactions, compare against monthly budget
2. **Net worth & investments** — track accounts and balances over time
3. **Bills & cash flow** — monitor recurring payments and upcoming cash needs

## Workflows (planned)

- Pull transactions via the bank connector and categorize them
- Refresh budget actuals monthly
- Update net-worth snapshot monthly
- Live dashboard artifact that refreshes from the connector
