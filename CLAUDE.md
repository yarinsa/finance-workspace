# Finance Workspace — project guide

Personal finance workspace for a single household. Aggregates Israeli bank and
credit-card data into **one deduped, queryable transaction ledger** plus a
net-worth/debt snapshot. Currency is ILS (₪) throughout.

> **Read `MEMORY.md` first (if present).** It is the project-local, gitignored
> household memory — real personal facts the scraped data can't infer (birth date,
> loan notes like the Leumi 2529 refund, active mortgage freeze). It is part of the
> project architecture, standalone from the user's machine-global Claude memory.
> When the user tells you a durable fact the data can't show, record it there.
> On a fresh clone `MEMORY.md` won't exist — seed it from the committed template:
> `cp MEMORY.example.md MEMORY.md`, then fill in real values.

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

Run `poetry run python data/digest.py` (or `--no-normalize` to combine existing normalized
output without re-scraping).

### Refreshing everything

The `refresh-all` skill orchestrates all nine sources end to end. It checks
every session **first** (`.claude/skills/refresh-all/scripts/check_sessions.sh`), batches the logins you need
into one pass, scrapes in dependency-correct order, then digests and forecasts.

Two things it encodes that are easy to get wrong:

- **Discount order is `account → mortgage → business`.** The three Discount apps
  share one login; the business (SME) app rebinds the server session and blocks
  the mortgage endpoints with `actionRequired: stepup`. Business last, always.
- **Never overwrite a good dump with error stubs.** A scrape against a
  half-authenticated session returns HTTP 200 with a few hundred bytes of error
  JSON. Verify the session is live *before* writing; stop rather than dump.

**The user logs in.** Credentials, OTPs and card numbers are never typed by an
agent, read from Keychain, or pulled from Messages — these are live bank
accounts, and unattended authentication is not a capability worth automating.
Chrome profiles persist logins, so this costs a login only when one lapses.

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

## The two things the app reads

- **`data/digested/transactions.json`** — the unified ledger. Every transaction
  across every source, **deduped on `(date, abs(amount))`**. Matched copies
  collapse into one row carrying `sources: [...]` (e.g. `["cal","riseup"]`).
  Includes a `summary` block: `total_spent`, `total_income`, `by_category`,
  `by_origin`. Query this for spending/category/cash-flow questions.
- **`data/digested/snapshot.json` / `snapshot.md`** — headline position: bank
  balances, credit-card debt, loans/mortgage, detected salary, totals, and a
  `spending` summary. Query this for net-worth/debt questions.

### Transactions database (Postgres)

A local Postgres (Docker Compose) holds the ledger in two layers: `scraped_transactions`
(replaced on every digest run) and `transaction_overrides` (manual category/note/excluded
edits, kept forever), read through the `transactions` view. When `DATABASE_URL` is set,
`data/digest.py` pipes the ledger through `db/ledger.py sync`, so `transactions.json`
reflects edits. Edit with `db/edit.py` (it rebuilds `data/digested/`); push with `sync-data`.
Setup, the orphaned-override rule and the `.env` rule are in **db/README.md**.
Override logic lives in `db/overrides.py` (shared by `edit.py` and the API); every change
writes an `override_audit` row (actor, field, old, new).

### Ledger API (editing from the dashboard)

The dashboard edits transactions through `api/` (FastAPI, compose service `api`, profile
`api`, `127.0.0.1:8787`), reached as `/api/*` on the same CloudFront domain via a Tailscale
Funnel to the Mac. Design, contract and rollout: **docs/ledger-api.md**; run/env: `api/README.md`.
Rules that keep it cheap and safe — keep them when changing anything here:

- **Every layer checks.** Edge-auth (Cognito) gates `/api/*` (401 JSON, not a redirect);
  the API requires CloudFront's `X-Origin-Secret` (≥32 chars), re-verifies the
  `plangram_session` id token, allow-lists emails, and needs the CSRF headers on writes.
- **The internet-facing process has no power.** The API container is non-root, read-only,
  gets only explicit env (never `env_file: .env`), and connects as Postgres role
  `finance_api` (overrides + audit only, never migrates). It holds no AWS or bank creds.
- **Publishing stays on the Mac.** An edit signals `LedgerRebuildWorkflow` (id
  `ledger-rebuild`, debounced 20 s) in the host worker, which runs the digest chain with
  `--no-normalize` and `publish_data`. Digests take `data/digested/.lock`.
- **Mac off = read-only.** The UI falls back to the static JSON and disables editing.
  Kill switch: `docker compose stop api` or `infra/tunnel.sh --off`.
- **The user does the outward steps**: installing/logging in to Tailscale, enabling Funnel,
  `terraform apply`, copying the secret into `.env`. SPA routing lives in the edge-auth
  Lambda (not CloudFront error responses, which would swallow API 403/404s).

### Automated sync (Temporal) — POC

**Proof of concept** (dev server, no persistence guarantees); see
`sync/README.md` for status. Not yet the only refresh path — `refresh-all` remains.

`sync/` runs `FinanceSyncWorkflow` daily at 07:30 Asia/Jerusalem over every scraped
source (discount, discount-mortgage, discount-business, leumi, cal, amex, harel, more,
analyst; RiseUp is out of scope) with the Temporal dev server in Docker Compose
(`docker-compose.yml`) and the worker under launchd. It checks **every** session
first, sends **one** macOS notification listing
the dead logins (grouped by login), and waits up to 12h
for `poetry run python sync/resume.py [source|group ...]`; still-dead sources are skipped as
`needs_login`, never fatal. Live sources are scraped one at a time in registry order
(Discount **business → mortgage → account**: the one Chrome app first, then the two
self-login sources), each followed by
a `data/validate.py dump <source>` gate (skipped while that file doesn't exist); one
failing source never stops the rest. Then digest chain once and
`infra/deploy.sh --data-only` once (when `SYNC_PUBLISH=1`; withheld if a dump was
rejected). It never authenticates a Chrome session. **One exception:**
Discount mortgage and checking are scraped by `scrapers/discount/scrape-mortgage.mjs` and
`scrape.mjs` (shared `lib.mjs`), which log in headless with
`DISCOUNT_ID`/`DISCOUNT_PASSWORD`/`DISCOUNT_NUM` from `.env` (check mode `self`, no
Chrome) and write the same raw files as the CDP `dump.sh` scripts; a refused login becomes
`needs_login` (and skips the other self-login source, which shares the credentials). They run
after the Chrome app (business) because their login may end the human's telebank session.
The source registry is `sync/sources.py`.
Every source's progress (checking_session → waiting_for_login → scraping → validating →
digesting → publishing → done, or needs_login / failed / rejected) is published as its own
entry to `data/sync-status.json`, which the app polls for a live status on `/syncs`, the
header dot and the home list.
Install with `sync/install.sh`; UI at http://localhost:8233. `temporalio` is in the
Poetry `sync` group.

### Freshness targets

`data/freshness.py` holds a per-source target (max age + grace) instead of one
global staleness rule: banks and cards **daily** (24h + 12h), the mortgage/loans
**weekly** (7d + 2d), pension/study/gemel **monthly** (30d + 7d). RiseUp has no
target and is never listed. Age is the newest `raw/` file mtime (what
`digest.source_syncs` calls `last_synced`). State is `fresh` -> `due` (past target,
inside grace) -> `overdue` (past grace; raises the home "נתונים לא עדכניים"
action, naming how late each source is) or `never`.

- `poetry run python data/freshness.py` prints the table (`--json` for the list; `--root DIR`
  reads another checkout's dumps read-only). `digest.py` writes the same list to
  `snapshot.json` -> `freshness`.
- `due_sources(now)` is the pure "scrape these today" list for the scheduled sync,
  in Discount-safe order (account -> mortgage -> business). A new source must be
  added to `TARGETS` (a test enforces it).

### Cashflow forecast

`poetry run python data/forecast.py` writes `data/digested/forecast.{json,md}` — a
multi-month cashflow projection (`HORIZON` months, currently 6) built from
RiseUp's forward-looking budget envelopes (not ledger extrapolation, which the
dedup key makes unreliable), with CAL/AMEX committed billings as a non-summed
cross-check. Month 1 is high-confidence; later months are an envelope
carry-forward. The **mortgage** installment comes from `sum(LoanEntry[].NextPayment)`
in the mortgage dump (not RiseUp's residual figure), and is **freeze-aware**: if
`data/freeze.json` exists (written by `data/detect_freeze.py`), post-freeze months
use the recomputed full payment. Read-only over scraped data; safe to re-run.
Rationale and the trust/double-counting decisions are in
`docs/forecast-architecture.md`.

### Balance runway

`data/runway.py` (called from `cashflow.py`, output in `cashflow.json` → `runway`)
projects the **combined Discount + Leumi checking balance day by day** for 45 days:
recurring ledger items (≥2 of the last 3 months) re-posted on their day of month,
Fri/Sat → Sunday. It reports the low point before payday, overdraft breaches and
**safe-to-spend**. It is bills-only (no discretionary spend), and card bills are
estimated from last month's bill. The app shows it at `/runway`.

Mint-style monthly views (`docs/plangram-prd/12-mint-cashflow.md`) are generated
from RiseUp's current budget the same way and written to `cashflow.json`:
`bills.py` (fixed envelopes as paid/upcoming/overdue, shown on `/runway`),
`budgets.py` (tracking-category plan vs. actual per RiseUp cycle, `/budgets`;
optional overrides in gitignored `data/budgets/budgets.json`), and `spending.py`
(per-month category/merchant/transaction breakdown with excluded buckets, `/spending`).
`actions.py` derives the home page's "לטיפול" list (limit breach, over-budget, overdue bills,
upcoming card bills, duplicate services, stale syncs) from those blocks, with period-stable ids.

**Budget overrides.** Each budget category carries `history` (spend of the last 4
RiseUp cycles, from `data/riseup/raw/budget_YYYY-MM_6.json`). To change a planned
amount: `poetry run python data/budgets.py set "<category>" <amount>`, `unset "<category>"`, or
`list`; it edits gitignored `data/budgets/budgets.json`, reruns `cashflow.py` and
prints the new line. The app's budget editor sheet is read-only and only shows this
command; push the result with `sync-data`.

### UX references

Before designing a dashboard screen, read `docs/ux-references.md`: Mobbin
patterns per feature, what the app has vs. lacks, and the design principles
(one number + verdict first, balance-after per row, label confidence).

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

### Household-specific facts (not derivable from the data)

Facts true for this household that the pipeline cannot infer — e.g. a loan whose
interest is refunded to ~0% effective, or an active mortgage freeze — live in the
project-local **`MEMORY.md`** (gitignored). Read it each session and honour it;
record new durable facts there rather than inlining them here, so this committed
guide stays about *method* and `MEMORY.md` holds the personal specifics.

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
| `harel` (pension + study funds) | ✅ | savings |
| `more` (More study funds, incl. self-employed) | ✅ | savings |
| `analyst` (Analyst קופת גמל, self-employed) | ✅ | savings |

RiseUp's `transactions` come from its budget envelopes (`actuals` + `excluded`) and
are the category-tagged copies used for dedup priority above. amex/cal emit a full
card roster (last4, name, active) without a balance — `digest.py` uses RiseUp's
debt-bearing cards for totals and enriches them with the roster names by last4.

## Conventions

- **Money out is negative**, income/refunds positive, across all normalized output.
- Each `normalize.py` must stay self-contained (its only shared import is
  `finance.models`) and idempotent — re-runnable after
  any scrape with no external state.
- Adding a source: scaffold with `add-bank-source`, write its `normalize.py` to the
  common envelope, emit a `transactions` entity if it has one, and `digest.py` picks
  it up automatically (no wiring needed). If the source overlaps RiseUp, add its
  origin name to `RISEUP_ORIGIN`.
- Credentials live in `.env` / `.mcp.json` (gitignored) — never commit secrets.

## Python environment and models (Poetry + Pydantic + SQLModel)

One Poetry project (`pyproject.toml`, in-project `.venv`) covers `data/`, `db/` and
`sync/`; run everything with `poetry run python …` (or `.venv/bin/python`). Plain
`python3` no longer works for normalizers or digest.

- **`finance/models.py`** — Pydantic models for every normalized entity
  (`Transaction`, `Account`, `CreditCard`, `Loan`, `Savings`, `Income`,
  `Subscription`) and the digested `LedgerTransaction`. Every `normalize.py` writes
  through `write_envelope`, which validates; records are `extra="forbid"`, so a
  **new field must be declared in the model first**. Dates are typed (ISO,
  ISO datetime and Discount's `YYYYMMDD` all parse; `""` is null).
- **`finance/tables.py`** — the Postgres tables as SQLModel classes; the schema's
  source of truth. Migrations are Alembic (`db/migrations/`), applied by
  `db/ledger.py` on every connect. Changing a table:
  `poetry run alembic -c db/alembic.ini revision --autogenerate -m "…"`, review,
  commit. `db/tests/test_schema.py` fails when the migrated DB and the models drift.
  The full procedure is the `schema-change` skill.

## Testing

The pipeline's pure logic is covered by **pytest**, driven by *real cases* — every
test mirrors an actual reconciliation decision (a specific Hebrew description, a
real dedup collision), not synthetic edge cases. Tests live in `data/tests/` and
import the scripts directly (`import digest`, `import cashflow`); `data/conftest.py`
puts `data/` on the path. Run them with:

```
poetry install --with sync,dev   # first time only (in-project .venv, see poetry.toml)
poetry run pytest                # run the suite
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
