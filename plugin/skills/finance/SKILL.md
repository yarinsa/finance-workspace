---
name: finance
description: Answer questions about your money — spending, cashflow, income, net worth, debt, savings, goals, forecast, retirement — by reading the digested finance data. Activate when the user mentions finances, spending, income, budget, balance, salary, subscriptions, debt, net worth, loans, mortgage, savings, pension, goals, forecast, retirement, or cashflow.
---

# Finance — your money, answered from chat

This is the **read layer** of the finance workspace: instead of a dashboard app,
you answer money questions directly from the pipeline's digested JSON. One digest
run produces everything; you read it and respond in plain language.

## Where the data lives

Resolve the data directory in this order (matches `scripts/_paths.py`):

1. `$FINANCE_DATA_DIR`
2. `finance.config.json` → `"data_dir"`
3. `./data` (default)

Digested outputs are under `<data_dir>/digested/`:

| File | Holds |
|---|---|
| `transactions.json` | unified deduped ledger + `summary` (total_spent, total_income, by_category, by_origin) |
| `snapshot.json` | balances, card debt, loans/mortgage, `savings[]` (pension/study funds), `totals`, detected salary |
| `cashflow.json` | `metrics[]`, `today{income,expense,net}`, `months[]`, `projection` |
| `forecast.json` | next-3-month cashflow forecast |
| `goals.json` | `general[]` (4 goal cards) + `personal_goals[]` |

Read them with the file tools or `python3 -c`. If none exist, tell the user to run
`/finance-refresh` (scrape) then `/finance-digest` (build).

## Digest → question map

Map the user's question to the feature and the file(s) that answer it. (Features
mirror `docs/plangram-prd/`.)

| Question is about… | Read | Key fields |
|---|---|---|
| **Spending / categories** ("how much on food last month") | `transactions.json` | `summary.by_category`, filter `transactions[]` by date/category |
| **Income / salary** | `transactions.json`, `snapshot.json` | `summary.total_income`, `totals.detected_monthly_salary` |
| **Cashflow** ("am I positive this month") | `cashflow.json` | `today{income,expense,net}`, `metrics[]`, `months[]` |
| **Net worth / debt** | `snapshot.json`, `cashflow.json` | `totals.*`, `projection.net_worth_today` |
| **Savings / pension / study funds** | `snapshot.json` | `savings[]`, `totals.long_term_savings` |
| **Loans / mortgage** | `snapshot.json` | `loans[]`, `totals.{mortgage_balance,consumer_loan_balance,monthly_loan_service}` |
| **Goals / emergency fund / inheritance** | `goals.json` | `general[]`, `personal_goals[]`, `missing_piece` |
| **Forecast / next month** | `forecast.json` | `months[]` |
| **Retirement / lifetime projection** | `cashflow.json` | `projection.{net_worth_at_retirement,focal_points[]}` |
| **Overview / "how am I doing"** | `snapshot.json` + `cashflow.json` | balances + `today` + top `metrics[]` |
| **Metrics catalog** | `cashflow.json`, `goals.json` | `metrics[]`, goals `general[]` |

## Autonomy tiers

Follow the same policy as the `riseup` skill:

- **Auto-run (no confirmation):** any *read* — parsing the digested JSON, and
  running the read-only digest scripts to refresh a stale output:
  `python3 scripts/cashflow.py`, `scripts/forecast.py`, `scripts/goals.py --list`.
- **Confirm first:** `/finance-refresh` (opens a browser to re-scrape) and a full
  `/finance-digest` re-run with normalization.
- **Always ask before writing:** any goal mutation
  (`scripts/goals.py --set-* / --add / --edit / --remove`). Show the exact command
  and its effect, and wait for an explicit yes.

## Output conventions

- Currency is **₪ (ILS)**; format with thousands separators (`₪16,700`).
- **Money out is negative** in the data; present expenses as positive magnitudes
  unless the sign is the point.
- Category names are **Hebrew** — echo the Hebrew and add an English gloss for
  English-speaking users (e.g. `כלכלה (groceries)`). Common ones:
  כלכלה=groceries, אוכל בחוץ=eating out, רכב=car, דיור=housing, משכנתא=mortgage,
  הלוואות=loans, ביטוח=insurance, חשבונות=bills.
- Always state **freshness**: quote `generated_at` and, when relevant, which
  `sources`/`by_origin` contributed. If the snapshot is more than ~7 days old, note
  it and offer `/finance-refresh`.
- Answer the question first, briefly; offer the drill-down, don't dump raw JSON.

## Graceful degradation

Answer per-feature from whatever exists. **Never hard-fail on one missing file.**

- Missing `goals.json` → answer cashflow/net-worth normally; say goals aren't set up
  and offer `/finance-goal --list`.
- Missing `projection` in `cashflow.json` → skip retirement/lifetime answers, still
  answer this-month cashflow.
- A digest older than the raw data (compare `generated_at`) → answer, but flag it
  and suggest `/finance-digest`.
- Asset classes we don't capture (real-estate, external portfolios) → say so; don't
  invent them. `savings[]` covers pension/study funds only.

## Related

- `/finance-refresh` — re-scrape a source (manual browser login).
- `/finance-digest` — rebuild all digested outputs.
- `/finance-goal` — set targets / add / edit / remove personal goals.
- `riseup` skill — RiseUp-native queries and write ops (classify/rename/exclude).
