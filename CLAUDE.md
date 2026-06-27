# Finance Workspace — project guide

Personal finance workspace for a single household. Aggregates Israeli bank and
credit-card data into **one deduped, queryable transaction ledger** plus a
net-worth/debt snapshot. Currency is ILS (₪) throughout.

## Intent

The goal is to answer plain questions about money — *"how much did I spend on
food last month"*, *"what's my total debt"*, *"what's my monthly loan service"* —
from a single normalized source the app reads, instead of querying each bank
separately. RiseUp is a paid aggregator that already pulls most sources; we scrape
it **and** the underlying institutions directly, then reconcile the overlap.

## Pipeline

```
data/<source>/raw/  --(<source>/normalize.py)-->  data/<source>/normalized/*.json
                                                          |
                                                  data/digest.py
                                                          |
                              data/digested/{transactions.json, snapshot.json, snapshot.md}
```

1. **Refresh** — each source has a skill (`<source>-refresh`) that drives a
   logged-in Chrome over CDP and dumps authenticated API responses into
   `data/<source>/raw/`. New sources are scaffolded with the `add-bank-source` skill.
2. **Normalize** — each source's self-contained `normalize.py` reads `raw/` and
   emits one common envelope per entity:
   `{"source", "entity", "generated_at", "records": [...]}`.
   Safe to re-run after every scrape; dedupes within the source by stable id.
3. **Digest** — `data/digest.py` runs every `*/normalize.py`, then combines all
   `normalized/*.json` into the consolidated outputs in `data/digested/`.

Run `python3 data/digest.py` (or `--no-normalize` to combine existing normalized
output without re-scraping).

## The two things the app reads

- **`data/digested/transactions.json`** — the unified ledger. Every transaction
  across every source, **deduped on `(date, abs(amount))`**. Matched copies
  collapse into one row carrying `sources: [...]` (e.g. `["cal","riseup"]`).
  Includes a `summary` block: `total_spent`, `total_income`, `by_category`,
  `by_origin`. Query this for spending/category/cash-flow questions.
- **`data/digested/snapshot.json` / `snapshot.md`** — headline position: bank
  balances, credit-card debt, loans/mortgage, detected salary, totals, and a
  `spending` summary. Query this for net-worth/debt questions.

### Next-month forecast

`python3 data/forecast.py` writes `data/digested/forecast.{json,md}` — a
next-month cashflow projection built from RiseUp's forward-looking budget
envelopes (not ledger extrapolation, which the dedup key makes unreliable), with
CAL/AMEX committed billings as a non-summed cross-check. Read-only over scraped
data; safe to re-run. Rationale and the trust/double-counting decisions are in
`docs/forecast-architecture.md`.

### Dedup rules (important)

- Two records are the **same purchase** when `date` and `abs(amount)` match.
- **RiseUp is the higher-priority copy** — it carries a spending `category` the raw
  bank/card dumps lack, so on a conflict RiseUp's fields win; the direct source is
  still recorded in `sources` and backfills anything RiseUp is missing.
- RiseUp's origin names are mapped to our source ids (`RISEUP_ORIGIN` in
  `digest.py`): `cal`/`leumicard` → `cal`, `americanexpress`/`isracard` → `amex`,
  `leumiBank` → `leumi`, `discount` → `discount`.
- Tradeoff of the date+amount key: a card charge and its matching bank debit on the
  same day/amount merge into one row. That is intentional — it's the same money in
  two ledgers — but it means `origin` is best-effort, not authoritative.

## Sources

| Source | normalize.py | Entities emitted |
|---|:--:|---|
| `discount` (personal checking) | ✅ | accounts, transactions |
| `discount-business` (SME checking) | ✅ | accounts, credit_cards, transactions |
| `discount-mortgage` (mortgage + loans) | ✅ | loans |
| `leumi` (checking + loan total) | ✅ | accounts, loans, transactions |
| `cal` (CAL credit cards) | ✅ | credit_cards, transactions |
| `amex` (American Express / Isracard) | ✅ | credit_cards, transactions |
| `riseup` (aggregator) | ✅ | accounts, credit_cards, income, subscription, transactions |

RiseUp's `transactions` come from its budget envelopes (`actuals` + `excluded`) and
are the category-tagged copies used for dedup priority above. amex/cal emit a full
card roster (last4, name, active) without a balance — `digest.py` uses RiseUp's
debt-bearing cards for totals and enriches them with the roster names by last4.

## Conventions

- **Money out is negative**, income/refunds positive, across all normalized output.
- Each `normalize.py` must stay self-contained and idempotent — re-runnable after
  any scrape with no external state.
- Adding a source: scaffold with `add-bank-source`, write its `normalize.py` to the
  common envelope, emit a `transactions` entity if it has one, and `digest.py` picks
  it up automatically (no wiring needed). If the source overlaps RiseUp, add its
  origin name to `RISEUP_ORIGIN`.
- Credentials live in `.env` / `.mcp.json` (gitignored) — never commit secrets.

## Testing

The pipeline's pure logic is covered by **pytest**, driven by *real cases* — every
test mirrors an actual reconciliation decision (a specific Hebrew description, a
real dedup collision), not synthetic edge cases. Tests live in `data/tests/` and
import the scripts directly (`import digest`, `import cashflow`); `data/conftest.py`
puts `data/` on the path. Run them with:

```
python3 -m venv .venv && .venv/bin/pip install pytest   # first time only
.venv/bin/python -m pytest                              # run the suite
```

Current coverage: `digest.py` classifiers (internal-transfer / card-bill /
savings), `consolidate_transactions` dedup + merged-flag re-evaluation,
`spending_summary`, and `cashflow.py` bucketing + monthly aggregation.

**Bugs → tests (required).** When a money figure comes out wrong, the workflow is:
1. **Open a bug as a user story** — *"As the household, when I see `<real
   description>` on `<date>` for `<amount>`, it should be classified as `<X>`,"*
   capturing the concrete transaction that misbehaved.
2. **Add a failing regression test** against it first — paste the exact
   description/amount into the matching `data/tests/test_*.py` case (the files are
   organized so there's an obvious home), watch it fail.
3. **Then fix** the classifier/dedup/aggregation until it passes.

This keeps the test suite a growing ledger of every real misclassification we've
seen, so the same shekel never gets double-counted twice.
