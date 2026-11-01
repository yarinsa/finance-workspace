# Pipeline scripts: validation, cashflow, forecast, history

Loaded when working under data/. Project overview: the root CLAUDE.md. Taxonomy and offsets: finance/CLAUDE.md.

**The compute lives in `finance/views/`, not here.** The `data/*.py` scripts load files, call
the pure builders (`runway`, `bills`, `budgets`, `spending`, `months_view`, `actions`,
`history`, `projection`, `forecast`, `goals`, `snapshot`) and write the outputs; the module
names below refer to `finance/views/<name>.py` unless a `data/` path is given. `cashflow.py`
builds `finance.views.household.Household` from `data/inputs.py`. Tests import the builders
from `finance.views`. A refactor that must not change figures is checked with
`scripts/parity/run.sh` (docs/json-to-db-migration.md, "Parity harness").

### Validation

`data/validate.py` proves the scraped data is complete and consistent, using the
**direct bank and card sources only** (no check reads `data/riseup`), so the
forecast can stop depending on RiseUp. Checks are organized by transaction type;
each returns `{id, type, status: pass|warn|fail|skip, summary, details[]}` and the
details name the concrete transactions (date, Hebrew description, amount, source)
behind any warn or fail.

| Type | Check id | What it proves | Data it relies on |
|---|---|---|---|
| dump | `dump.<source>` | The fresh dump is trustworthy: no error stubs / missing or tiny required files, no >20% record-count drop vs the previous `normalized/` output (a CAL billing-cycle rollover is only a warning), latest transaction not stale | each source's `raw/` + a throwaway dry-run of its `normalize.py` |
| card_bill | `card_bills` | Every CAL/AMEX statement (cycle and immediate charges) is settled by one bank debit (same amount, ±3 banking days, Fri/Sat roll to Sunday), and every issuer-named card-bill debit has a statement; also flags matches `digest.is_card_bill_payment` misses | CAL `monthlyDebitsSummary`, AMEX monthly pulls, bank ledgers |
| card_statement | `card_statements.cal` / `.amex` | A card cycle's transactions sum to its statement total (catches pagination gaps, installments and foreign-currency rows carried at the wrong ₪ amount) and every raw AMEX voucher reached the ledger | CAL `cardTransactions_*`, AMEX `transactions_*`, normalized card transactions |
| balance | `balance.<account>` | Opening balance + operations = closing balance (running-balance chain has no break, ends on the current balance), the normalized ledger sums to the same movement, and no multi-week hole in history | Discount/Leumi/business `raw/transactions.json` running balances |
| internal_transfer | `internal_transfers` | Each move between our own accounts has its opposite leg within 2 banking days (transfers to untracked accounts — Hapoalim/Bit, liquid deposit — are not orphans) | all bank ledgers |
| loan_payment | `loans.mortgage` / `.discount` / `.leumi` | The dump's `NextPayment` (mortgage = Σ per track, as `forecast.py` uses) matches the actual bank debit in the expected month, and the prior installments exist | mortgage/loan dumps, bank ledgers |
| salary | `salary` | The payday income `runway.py` infers arrived in its window in each of the last 4 months | bank ledgers (via `runway.infer_recurring`) |

Findings are attributed, not just counted: a statement or transfer that cannot be
found because a bank ledger has a hole (or predates it) is reported as a
`warn`/skip pointing at the hole, so one root cause does not fan out into dozens of
failures.

```
poetry run python data/validate.py                  # all checks -> data/digested/validation.{json,md}
poetry run python data/validate.py dump <source>    # exit 0 = ok, 1 = REJECT (run before trusting a scrape)
poetry run python data/validate.py --data-dir D --out-dir O --as-of 2026-10-16 [--strict]
```

`--data-dir` / `FINANCE_DATA_DIR` reads another checkout's data read-only;
`--out-dir` / `VALIDATE_OUT_DIR` redirects the report. `validation_actions(report)`
returns "לטיפול"-shaped action items for the failures (wire-up into `actions.py`
is separate). The suite is `data/tests/test_validate.py`.

**Real failures become regression tests**, same rule as below: a `fail` that turns
out to be a real defect (e.g. Leumi FITID collisions dropping ledger rows, CAL
`trnAmt` instead of the billed ₪) gets a failing test built from the exact
records, then the fix.


### Cashflow forecast

`poetry run python data/forecast.py` writes `data/digested/forecast.{json,md}` — a
multi-month cashflow projection (`HORIZON` months, currently 6) built from
RiseUp's forward-looking budget envelopes (not ledger extrapolation, which the
dedup key makes unreliable), with CAL/AMEX committed billings as a non-summed
cross-check. Month 1 is high-confidence; later months are an envelope
carry-forward. The **mortgage** installment is the sum of the Discount mortgage tracks'
`monthly_payment` (the dump's `NextPayment`, due on `next_payment_date`), read from the stored
`loans` (snapshot.json's loans until a digest after migration 0025 fills the date), not RiseUp's
residual figure, and is **freeze-aware**: if
`data/freeze.json` exists (written by `data/detect_freeze.py`), post-freeze months
use the recomputed full payment. The freeze and the bank's schedule bands live in Postgres
(`loan_freezes`, `mortgage_schedule_periods`, `db/input_store.py`; `import` copies the old
`freeze.json` / `mortgage_schedule.json` in, and the files are read only while a table is empty). Read-only over scraped data; safe to re-run.
Rationale and the trust/double-counting decisions are in
`docs/forecast-architecture.md`.

### Balance runway

`finance/views/runway.py` (`Household.runway`, output in `cashflow.json` → `runway`)
projects the **combined Discount + Leumi checking balance day by day** for 45 days:
recurring ledger items (≥2 of the last 3 months) re-posted on their day of month,
Fri/Sat → Sunday. It reports the low point before payday, overdraft breaches and
**safe-to-spend**. It is bills-only (no discretionary spend), and card bills are
estimated from last month's bill. The app shows it in the month screen's תחזית view
(`/monthly?view=forecast`; `/runway` redirects there) and as a chart on the home page.

Mint-style monthly views (`docs/plangram-prd/12-mint-cashflow.md`) are written to
`cashflow.json`. They read the ledger's `category` / `kind` (see "Categories and kind");
RiseUp's budget still supplies the *plan*:
`bills.py` (`/monthly`) — built from the **ledger**, not RiseUp: a bill is a series
(merchant + amount ±15%) of kind=fixed rows active in 2 of the last 3 cycles (3 when only
the category's default made it fixed), plus utilities (electricity/water/gas/ארנונה) on
their own cadence (bi-monthly water is due every other month, amount = median of the
last three, `estimated`); paid/upcoming/overdue, kind = `categories.bill_kind`. RiseUp
gives only the cycle's start day. `budgets.py` — one line per **our category** (or group, e.g.
תחבורה), planned = RiseUp's tracking envelope through `tracking_category` or the override,
spent = the cycle's `kind == "variable"` ledger rows of that category (refunds subtract,
floored at 0), `estimate` = median of the last 3–6 cycles, plus `summary`: the cycle in
**three blocks** — fixed (kind=fixed actual, expected adds the monthly charges of the last
two cycles not seen yet), variable (actual vs Σ per-category median), debt_savings (loans,
mortgage, savings), **`left` = free money**: income − fixed − debt_savings − the
variable *plan* (the budget lines' total) — what is not assigned to anything, aimed at
~0 — and `projected_end`: the same with variable at `projected` = actual + the estimate ×
the share of the cycle still ahead (a daily run-rate, so a trip-heavy median doesn't
swamp the last days). Fixed/debt at expected; income at max(actual, the forecast's). `spending.py`
(per-month category/merchant/transaction breakdown with excluded buckets; every row carries
the ledger's `kind`, `group` = `category_group` and `block` — fixed / variable / debt_savings,
the `months_view.classify_expense` rule — plus `by_line` per section/group/category).
`cashflow.fixed_expenses` (the "what can I cut?" review, shown inline in /monthly's קבוע section) is the month's kind=fixed ledger
rows plus the still-expected monthly ones (`budgets.fixed_items`), grouped by
`categories.lever` (fees → subscriptions → bills → installments → committed → other).
`actions.py` derives the home page's "לטיפול" list (limit breach, over-budget, overdue bills,
upcoming card bills, duplicate services, stale syncs) from those blocks, with period-stable ids.


**Budget overrides.** Each budget line carries `history` (its ledger spend in the last 4
cycles). To change a planned
amount: `poetry run python data/budgets.py set "<category>" <amount>`, `unset "<category>"`, or
`list`; it edits the `budget_lines` table (`db/budget_store.py`; the old gitignored `data/budgets/budgets.json` is read only until `poetry run python db/budget_store.py import` copies it in) (a RiseUp envelope name is stored as
our category; a category RiseUp has no envelope for adds a line), reruns `cashflow.py` and
prints the new line. The budget editor in the `/monthly` category sheet is read-only and only shows this
command; push the result with `sync-data`.


### History and the property asset

Scraped sources only know today, so `finance/views/history.py` (`Household.history`; loaders and `backfill` in `data/history.py`; output in
`cashflow.json` → `history`) rebuilds the past for the home screen's lenses:
`cash` (end-of-day Discount + Leumi checking, the runway's pool, last 90 days: days inside a
bank's running-balance chain are measured, earlier days are walked back through its ledger;
`measured_from` marks the line), `debt` (month-start loan balances, 12 months back by reverse
amortization, 36 ahead on `projection.amortize_loans`) and `positions` (one row a day in Postgres
`position_snapshots`, recorded by every digest; best-effort, a dead DB gives `[]`), which feed
the שווי נקי and חיסכון lenses. Older days can be seeded from the S3 object versions of
`data/snapshot.json` with `poetry run python data/history.py backfill FILE...`; it keeps only
snapshots whose accounts, loans and savings match today's (`history.coverage`).

The apartment is an **asset** typed in by hand (`assets` table, `db/asset_store.py`,
GraphQL `assetCreate` / `assetUpdate`; `valuation_source` is `manual` until an estimate exists).
The digest adds `snapshot.totals.property_value` and `net_worth_with_property`; the older totals
(`tracked_net_position`, `net_position_with_savings`) keep their meaning.

### Long-range projection

`poetry run python data/projection.py` writes a net-worth projection to retirement/end age.
`current_age` is derived from `BIRTH_DATE` at the top of the file (not in scraped
data). **If `BIRTH_DATE` is missing or looks wrong, ask the user for their birth
date** rather than guessing — a wrong age shifts every loan-payoff and retirement
milestone.

### Saving money — how to answer "where/how can I save?"

When the user asks how to save money, work from their **real line items**, not
generic advice. There are two distinct levers — cover both and say which applies:

1. **Easy recurring cuts (lowest lifestyle impact).** Scan the fixed/recurring
   envelopes and the ledger for: waivable **bank/card fees** (עמלות, `דמי כרטיס`),
   **duplicate services** (e.g. two international-call plans; Spotify overlapping
   an Apple Music bundle; overlapping streaming), and **unused subscriptions**.
   Quote the actual Hebrew description + ₪ amount, rate each by ease
   (trivial/easy/moderate), and total the picks into ₪100 / ₪300 / ₪500 tiers.
2. **Loan prepayment for cashflow.** To make the *forecast* more positive, a lump
   sum should reduce the **monthly payment**, which requires two things: pick a
   **Schpitzer (annuity)** loan (a 0%/fixed-principal loan prepayment only shortens
   the term — no monthly relief), and instruct the bank to **הקטנת התשלום** (reduce
   the installment), **not** קיצור התקופה (shorten the term). Rank targets by
   ₪/mo freed per ₪1,000 deployed. **Never** recommend prepaying a loan whose
   interest is refunded/subsidised to ~0% effective (see household notes below).


### Savings are assets, not cashflow (important)

Long-term savings vehicles (Harel pension + study funds, More study funds, Analyst קופת גמל) emit a **`savings`**
entity and **never a `transactions` entity**. A pension contribution is not
spending — emitting deposits into the ledger would inflate `total_spent`, and the
bank-side debit is already captured by the bank source anyway.

In `snapshot.json` these sit in their own `savings` block. `tracked_net_position`
deliberately **excludes** them (it stays a liquid-position-vs-debt figure);
`net_position_with_savings` is the one that includes them. Keep that split — the
two answer different questions ("can I pay my bills" vs "what am I worth").


### Dedup rules (important)

- Two records are the **same purchase** when `date` and `abs(amount)` match. One
  exception (`digest.merge_shifted_copies`): a RiseUp-only row and a direct row one day
  apart with the same origin, amount and merchant merge (RiseUp dated APPLE ₪59.50 a day
  after Max); the direct source's date is kept.
- **RiseUp is the higher-priority copy** — it carries the spending label and budget
  envelope the raw bank/card dumps lack (inputs to the category, see above), so on a
  conflict RiseUp's fields win; the direct source is
  still recorded in `sources` and backfills anything RiseUp is missing.
- RiseUp's origin names are mapped to our source ids (`RISEUP_ORIGIN` in
  `digest.py`): `cal` → `cal`, `leumicard` → `max` (Max, ex-Leumi Card), `americanexpress`/`isracard` → `amex`,
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
| `max` (Max, ex-Leumi Card) | ✅ | credit_cards, transactions |
| `riseup` (aggregator) | ✅ | accounts, credit_cards, income, subscription, transactions |
| `harel` (pension + study funds) | ✅ | savings |
| `more` (More study funds, incl. self-employed) | ✅ | savings |
| `analyst` (Analyst קופת גמל, self-employed) | ✅ | savings |

RiseUp's `transactions` come from its budget envelopes (`actuals` + `excluded`) and
are the category-tagged copies used for dedup priority above. amex/cal emit a full
card roster (last4, name, active) without a balance — `digest.py` uses RiseUp's
debt-bearing cards for totals and enriches them with the roster names by last4.

### Source manifests

Each source declares itself in `data/<source>/manifest.json`: `name`, Hebrew `label`,
`account_types` (checking, credit_card, pension, …) and `capabilities` (the normalized
entities it provides). Model and loader: `finance/manifest.py`. The sync registry
(`Source.label`/`.manifest`, `LABEL_HE`), `digest.source_syncs` and `snapshot.source_manifests`
read it, and the app takes labels from the snapshot (`sourceLabel` in `app/src/lib/data.ts`).
A new source adds its manifest (a test enforces it). Editing or adding manifests: the `source-manifest` skill.

`connection` is the source's connection form as a JSON Schema: one string property per `.env`
variable the scraper reads (`x-env` names it, `writeOnly` marks a secret; a test checks each
against the scraper's `process.env.*`). The `/syncs` row renders it with react-jsonschema-form
(`app/src/components/ConnectionForm.tsx`, lazy-loaded) **read-only**: the app shows what a
source needs, but values stay in the Mac's `.env` and never pass through the API.

