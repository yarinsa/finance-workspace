# Digested JSON → Postgres tables + GraphQL

Status: **phases 0 and 1 done, phase 2 slice 1 done** (2026-11-01). Branch `claude/json-tables-graphql-migration-9223cd`.

Moves every digested JSON (`data/digested/*.json`) and every hand-kept side file into typed
Postgres tables, serves everything the dashboard reads through schema-first GraphQL, and deletes
the static `/data/*.json` path. Per-source `raw/` and `normalized/` dumps stay files: they are the
scrapers' output and the normalizers' contract, not app data.

## Decisions already taken

| # | Decision | By |
|---|---|---|
| D1 | The app requires the API. No static JSON fallback, no offline data cache. "Mac off" = the app shows a calm offline state. | user |
| D2 | Typed columns, not JSONB blobs. The one JSONB today that holds data (`scraped_transactions.record`) is split into columns too. | user |
| D3 | Everything is in scope: transactions, snapshot, cashflow, goals, forecast, validation, sync status, side files. | user |
| D4 | **Store inputs, compute outputs.** A table holds a fact the DB cannot derive: a scraped entity, a hand-typed input, or a time series that can't be rebuilt. Every figure that is a function of stored rows is computed in the resolver, by the same pure Python that computes it today. Nothing is stored twice. | this doc |
| D5 | **One field list per entity.** A SQLModel base class declares the fields once. The normalized record (`extra="forbid"`), the table row, and the GraphQL binding all use it. | this doc |
| D6 | **Migrate what is read, delete the rest.** A field survives only if the app, or another view, or a host job reads it. The consumption map below is the list. | this doc |
| D7 | **Parity first, no figure changes.** Each moved figure has to equal today's JSON on real data before the JSON stops being written. Any fix is its own bug-first change, after the move. The one planned exception is D8. | this doc |
| D8 | **RiseUp is deprecated.** It was a one-time import (last dump 2026-10-16) and is never refreshed again. Its normalized transactions stay in the ledger as a frozen archive: 1,063 rows that only RiseUp has, Mar–Oct 2026, so `RISEUP_ORIGIN` dedup stays. No new table is built from RiseUp. Everything that reads RiseUp's budget document today moves to household data in phase 2b. | user |
| D9 | Validation has no table: its failures go to the inbox, and the full report is the CLI. The `.md`/`.html` files become the `finance.report` CLI. The `subscriptions` entity is dropped. | user |

### Why D4 (computed views, not result tables)

- **Overlays go away.** `ledgerOverlay`, `goalsOverlay`, `holdingsOverlay` and `propertyOverlay`
  exist only because the JSON is stale until a rebuild publishes. If a resolver computes from live
  tables, an edit shows up on the next query.
- **The rebuild shrinks.** `LedgerRebuildWorkflow` and `publish_data` stop being on the read path.
- **No drift.** There are no result tables to keep in sync, and no "which copy is right" between
  `budgets.summary`, `months_view` and `spending`.
- **It is cheap.** The ledger is ~2.2k rows. `api/gql/ledger.py` already loads all of it per
  request and filters in memory. Every builder runs in milliseconds over that.

The cost is that every builder has to take its inputs explicitly (rows, entities, `today`) instead
of reading files. That refactor is phase 0.

## Consumption map → destination

Legend:
- **T** = new table (input).
- **V** = computed view (resolver).
- **X-dead** = no reader, delete.
- **X-dup** = duplicate of something kept, delete.

Exact field-level reads are in the app sections below each row; anything not listed there is dropped.

### transactions.json

| Key | Fate |
|---|---|
| `transactions[]` | Already in Postgres (`scraped_transactions` + layers → `transactions` view). Becomes typed columns (phase 3). Served by `Query.transactions`. |
| `summary` | X-dead for the app, and X-dup of `snapshot.spending`. Its only consumer is `snapshot.md`, which becomes the report CLI. |
| `category_merges` | X-dup (`categories.mergedInto`) |
| `generated_at`, `currency`, `note` | X-dead (`generatedAt` moves to `digest_runs`) |

### snapshot.json

| Key | Fate |
|---|---|
| `bank_accounts`, `credit_cards`, `loans`, `savings` | **T** `accounts`, `credit_cards`, `loans`, `savings_holdings` |
| `income` | X-dead, **dropped in phase 2**. Only RiseUp emitted it (D8). `totals.detected_monthly_salary` also fed the projection's retirement drawdown, but only when there is no forecast; that fallback now assumes 0, like the surplus one. The runway infers payday from the ledger. |
| `totals` | **V** `Snapshot.totals`. The 6 read fields plus `propertyValue`. `position_snapshots` keeps recording the subset it records today. |
| `debt_profile` | **V**, internal (assistant tool) |
| `assets` | X-dup (`Query.assets`) |
| `holding_assignments` | X-dup. It becomes `SavingsHolding.assignment` (read side of `holdingAssign`). |
| `syncs` | **T** `source_dumps`, surfaced on `SyncSource` |
| `source_manifests` | X-dup of `data/<src>/manifest.json`. Served as `SyncSource.label` / `.connection` (manifests are config, not table data). |
| `freshness` | X-dead. Its staleness goes into the action builder from `source_dumps`. |
| `spending`, `transactions_count`, `currency`, `note` | X-dead / X-dup |

### cashflow.json

| Section | Fate |
|---|---|
| `runway` | **V** `Query.runway` |
| `pace` (minus `expected`, `by_category`) | **V** `Query.pace` |
| `months_view` (minus `categories`) | **V** `Query.months` |
| `budgets` + `bills` + `fixed_expenses` | **V** `Query.cycle`: one budget cycle, three lists plus `summary`. They share one window and one input set today. |
| `spending.months[]` | Split. `transactions[]` becomes X-dup (`Query.transactions(filter:{dateRange})`). `by_category` / `by_merchant` become X-dup (`categories(dateRange)` / `merchants(dateRange)`, which already carry totals). What remains is **V** `Query.monthSummaries`: `month`, `total` and the `excluded` buckets. |
| `history` | **V** `Query.history`: `cash` from **T** `account_balance_days`, `debt` from loans, `positions` from `position_snapshots` |
| `projection` + `charts.net_worth` | **V** `Query.projection`: one simulation, which today is emitted twice in two shapes |
| `horizons` (minus `names`, `targets`, `goals`) | **V** `Query.horizonAllocation`. Names, targets and goals already come from `horizons` / `goals`. |
| `metrics` | **V** `Query.metrics` |
| `actions` | X-dup (`notifications` table). The builder stays as the host job that fills the inbox. |
| `generated_at` | `digest_runs.finished_at` → `Query.dataAsOf` |
| `today`, `months`, `charts.{income,expense}_breakdown`, `charts.trend`, `currency`, `current_month`, `note` | X-dead / X-dup |

### goals.json, forecast.json, validation.json, sync-status.json

| Key | Fate |
|---|---|
| `goals.general[]` | **V** `PlanTargets.cards` (computed fields next to the stored targets) |
| `goals.personal_goals[]` | **V** computed fields on the existing `Goal` type (`progressPct`, `onTrack`) |
| `goals.missing_piece` | **V** `PlanTargets.missingPiece` |
| `goals.liquid_buffer`, `monthly_surplus` | X-dead |
| `forecast.json` | **The app never reads it.** It stays as an internal view (`views.forecast`) because pace, cycle, months, projection and goals use it. Not in GraphQL. The CAL/AMEX "committed charges" cross-check is dropped from it (diagnostic only; `validate.card_bills` covers it). |
| `validation.json` | **The app never reads it.** Its only consumer is the action builder. There is no table: the host job runs `validate.run_all` and its failures become notifications. The full report is `poetry run python data/validate.py` (CLI, unchanged). |
| `sync-status.json` | X-dup (`sync_status` table + SSE). The app's static fallback goes. |

### Side files

| File | Fate |
|---|---|
| `data/budgets/budgets.json` | Already `budget_lines`. Delete the fallback read and the file. |
| `data/goals/goals.json` | Already `goals` + `plan_targets`. Move the `goals.py` CLI onto `db/goal_store.py`, then delete the file. Today the CLI edits a file that is ignored while the DB is up. |
| `data/offsets/rules.json` | **T** `offset_rules`. Human layer, imported once. |
| `data/mortgage_schedule.json` | **T** `mortgage_schedule_periods`. Human layer, imported once. |
| `data/freeze.json` | **T** `loan_freezes`, written by `detect_freeze.py` |
| RiseUp `budget_current.json` / `budget_YYYY-MM_6.json` | Read directly by forecast, budgets, bills and months_view today, and frozen since 2026-10-16. These reads are replaced in phase 2b (D8): the tracking envelopes are imported once into `budget_lines`, `cashflowStartDay` is imported once into `household_settings`, and no table is built from them. |
| Bank running balances (Discount/Leumi `raw/transactions.json`) | Raw stays. The bank normalizers emit a new `balance_days` entity, stored as **T** `account_balance_days`. |
| Normalized `subscriptions` entity | Read by nothing. Stop emitting it, no table. |

## Data model

All new tables follow the `docs/tenancy.md` checklist:
- `tenant_id` first in the PK and every unique key;
- forced RLS with the one `tenant_isolation` policy;
- an index leading with `tenant_id`;
- an entry in `OWNED` in `db/tests/test_tenancy.py` and in the conftest TRUNCATE list;
- a cross-tenant test.

`finance_api` gets **SELECT only** on machine tables, and SELECT plus the specific writes on human tables.

### Machine layer (replaced by every digest, one transaction)

| Table | Key | Columns (beyond the key) | From |
|---|---|---|---|
| `digest_runs` | `tenant_id, id` (serial) | `started_at, finished_at, normalized bool, transactions int` | digest.py |
| `accounts` | `tenant_id, institution, account_id` | `kind, label, balance, available_balance, overdraft_limit, sources text[]` | `Account` entities, reconciled (direct source beats RiseUp) as `build_snapshot` does today |
| `credit_cards` | `tenant_id, issuer, last4` | `name, holder, active, owed, next_charge_date` | `CreditCard` + `next_card_charges` (stays a digest computation: it reads pre-dedup rows) |
| `loans` | `tenant_id, position` | `lender, loan_id, name, category, balance, original_amount, rate_pct, rate_type, index_linked, payments_remaining, payments_total, monthly_payment, next_payment, final_date` | `Loan`. `loan_id` is nullable, so the key is the digest order, as with `scraped_transactions`. `next_payment` comes from the mortgage dump and replaces forecast's direct raw read. |
| `savings_holdings` | `tenant_id, holding_id` | `institution, kind, label, balance, liquid, liquidity_date, maturity_date, as_of, topic_id, work_state, policies_count, management_fee, yield_ytd` | `Savings`. `holding_id` = `institution:topic_id`, else the label: the same rule `holding_assignments` already keys on, so the two join with no FK (the machine/human split, as with overrides). |
| `account_balance_days` | `tenant_id, institution, account_id, date` | `balance` | measured end-of-day balances from the running-balance chains |
| `source_dumps` | `tenant_id, source, entity` | `record_count, latest_date, dumped_at` | normalized files' mtimes and counts (today's `source_syncs`) |
| `transaction_auto_offsets` | `tenant_id, txn_date, abs_amount, against_date, against_abs_amount` | `amount, rule` | `offsets.suggest`, now a table instead of `record->'auto_offsets'` |

`scraped_transactions` keeps its key and its replace-per-digest semantics. In phase 3 its `record`
JSONB becomes one typed column per `LedgerTransaction` field, and the `transactions` /
`transaction_kinds` views are rewritten over the columns.

### Human layer (kept forever, never truncated)

These already exist: `transaction_overrides`, `override_audit`, `tags`, `transaction_tags`,
`transaction_offsets`, `merchant_rules`, `budget_lines`, `goals`, `horizons`, `plan_targets`,
`holding_assignments`, `assets`, `notifications`' household columns.

New:

| Table | Key | Columns |
|---|---|---|
| `household_settings` | `tenant_id` (one row) | `cycle_start_day smallint`. Imported once from RiseUp's `cashflowStartDay`; the budget cycle (budgets, bills, `cycle`) starts on it. |
| `offset_rules` | `tenant_id, id` | `payer, against text[], note` |
| `mortgage_schedule_periods` | `tenant_id, from_month` | `to_month, payment, source` |
| `loan_freezes` | `tenant_id, loan_id` | `frozen_payment, resume_month, resume_payment, detected_at`. This one is machine-written, by `detect_freeze.py`, which deletes it on resume. |

### Time series (append or upsert, never rebuilt)

`position_snapshots` stays as it is.

## Model layering (D5)

Today the same entity is declared up to three times:
- `models.Account` is Pydantic with `float`;
- a future `tables.Account` would be SQLModel with `Decimal`;
- the dataclasses in `api/gql/ledger.py` mirror table columns again.

The `tables.py` docstring claims its columns are typed from `LedgerTransaction`, but they are hand-copied.

The rule after this migration:

```python
# finance/models.py: the field list, once. SQLModel without table=True is a Pydantic model.
class AccountFields(SQLModel):
    institution: str
    account_id: str
    kind: str
    balance: Money                      # Annotated[Decimal, sa_type=Numeric(12,2), JSON -> float]
    label: str | None = None
    ...

class Account(AccountFields, Record): ...          # normalized record, extra="forbid", write_envelope

# finance/tables.py: the row = the fields + tenancy and keys
class AccountRow(AccountFields, table=True):
    __tablename__ = "accounts"
    tenant_id: uuid.UUID = Field(sa_column=_tenant(primary_key=True))
    sources: list[str] = Field(sa_type=ARRAY(Text))
```

- **`Money` is one annotated type.** It is `Decimal` in Python, `Numeric(12,2)` in Postgres and a
  float in normalized JSON, so `normalized/*.json` stay byte-identical. That is guarded by a
  round-trip test over the real normalized files.
- **GraphQL binds to the row class.** That is the existing convention for DB-backed types
  (`Category`, `Goal`, `Asset`). `snapshot.graphql`'s six types re-bind from `models.*` to
  `tables.*Row`.
- **Computed views return Pydantic output models**, declared next to the builder
  (`finance/views/runway.py: class Runway(BaseModel)`). They hold only live fields (D6). The
  GraphQL types bind to them, so `test_graphql_schema` checks that the SDL, the models and the app
  agree.
- **`currency` is dropped from every model.** It is ILS everywhere and never read.

## Where the logic lives

The pure builders move from `data/*.py` into a package that the API, the host jobs and the CLIs all import:

```
finance/views/
  household.py     # Inputs + Household(inputs, today): one cached property per view; the loader fills Inputs
  snapshot.py      # totals, debt_profile          (from data/digest.py build_snapshot / loan_profile)
  forecast.py      # internal only                 (data/forecast.py)
  runway.py  pace.py  cycle.py (budgets+bills+fixed)  months.py  spending.py
  history.py  projection.py  horizons.py  goals.py  metrics.py  actions.py
```

- **Every builder is a pure function of explicit inputs plus `today`.** They do no file reads, no
  `date.today()` and no DB access inside a builder.
- **`Household` wraps today's per-request `Ledger`.** It is the one loader, and three kinds of
  consumer share it:
  - GraphQL, per request;
  - the host jobs: notifications sync, `position_snapshots`, the daily push;
  - the assistant (its `snapshot` tool works in the API for the first time).
- **Resolvers stay one line each**, because a cached property computes each view once per request:

  ```python
  def resolve_runway(self, _, info):
      return household(info).runway          # Runway model; fields read by default_resolver
  ```

- **`today` is the Israel-local date**, taken once per request in `Household`. Tests pass it explicitly.
- **`data/*.py` stay as thin CLIs** (`budgets.py set`, `validate.py`, `detect_freeze.py`, `history.py backfill`).
  `forecast.py`, `cashflow.py` and `goals.py` stop being pipeline steps. They become
  `poetry run python -m finance.report <snapshot|forecast|cycle|goals>`, which prints the same
  markdown the `.md` files hold today, from `Household`, for Claude and for the user.

## Pipeline after the migration

```
normalize (unchanged) ─► digest.py ─► ONE transaction: scraped_transactions + every machine table + digest_runs
                                  └─► after_digest job: position_snapshots row, validate.run_all,
                                      actions → notifications (inbox.sync), push
```

- **The digest DB write is fatal on failure.** The DB is now the only output. This is the ledger
  pattern, not today's best-effort snapshot and inbox writes.
- **`DIGEST_STEPS` becomes `digest.py → after_digest`.** `cashflow.build()` inside `digest.py` (it
  runs twice today, once on stale inputs) goes.
- **`LedgerRebuildWorkflow` after an API edit runs only `after_digest`.** Overrides, tags and
  offsets are applied by the views at read time, so a full digest is no longer needed for an edit
  to show. Phase 0 verifies that no digest-time stamp depends on an override; if one does, that
  stamp moves into the view.
- **Gone:** `publish_data`, the `infra/deploy.sh` data loop, and the S3 copy of `sync-status.json`.

## GraphQL surface (sketch; the real SDL comes per phase via the `graphql-schema` skill)

```graphql
extend type Query {
  dataAsOf: DateTime                      # last digest_runs.finished_at
  snapshot: Snapshot!                     # exists; now served. bankAccounts, creditCards, loans, savings, totals
  runway: Runway
  pace: Pace!
  months: MonthsView!                     # months_view
  cycle: BudgetCycle                      # budgets + bills + fixed_expenses + summary
  monthSummaries(first: Int, after: String, last: Int, before: String): MonthSummaryConnection!
  history: History!
  projection: Projection!                 # focal points + net-worth series
  horizonAllocation(first: Int, after: String, last: Int, before: String): HorizonMonthConnection!
  metrics: [Metric!]!
}
# Existing types gain fields:
#   Goal { progressPct onTrack }, PlanTargets { cards missingPiece },
#   Savings { holdingId assignment { horizon goal } },
#   SyncSource { label connection lastDumpedAt latestTxnDate entities },
#   Transaction { merchant kind cardLast4 accountId cardBillPayment internalTransfer savings }
```

**No `forecast` or `validation` field.** Nothing in the app reads them (D6).

**Relay pagination stays honest.** A list that can grow (`monthSummaries`, `horizonAllocation`) is a
connection. Small fixed lists inside a view object (`runway.days`, `cycle.bills`) are plain lists,
as `Snapshot.loans` is today.

## App cutover

- **`lib/data.ts`'s top-level `await loadAll()` goes.** In its place, each route has a Relay query
  for the views it shows, fetched with `useLazyLoadQuery` and Suspense.
- **The order is one route per PR**:
  1. home (`Overview`, `HomeBand`, `AccountCards`)
  2. `Monthly`
  3. `Transactions`
  4. `Savings` (with `Horizons`)
  5. `Timeline`
  6. `Metrics`
  7. `Syncs`
  8. `Inbox` (drop its static fallback)
- **Each route deletes its JSON reads and the TS interfaces in `data.ts` that only it used.**
- **`Transactions` stops filtering 2.2k rows client-side (`applyView`).** It moves onto
  `TransactionFilter` (adding the filters it lacks) with pagination.
- **After an edit, the mutation payload updates the Relay store** and the affected view queries
  refetch. Then the overlays, `useLedgerApi`'s rebuild polling, `markDirty`, `getDataVersion` and
  the REST helpers that only tests use are all deleted.
- **The last PR removes the plumbing:**
  - the service worker's `/data/*.json` cache;
  - the `vite.config.ts` data middleware;
  - `tenant.ts dataUrl`;
  - the edge-auth `/data/*` gate;
  - `SessionExpiredError`'s JSON heuristics. The API's 401 handling already covers it.

## Phases

Each phase is its own PR or PRs and is mergeable alone. Migrations are additive until the drop
steps, which are marked ⚠. Each migration needs your go-ahead on the shown plan before it touches
the live DB, because `db/ledger.connect` auto-migrates.

| Phase | Work | Done when |
|---|---|---|
| **0. Foundations** (no behaviour change) — **done 2026-11-01** | Move the builders into `finance/views/` with explicit inputs and `today`. `Household` loader (`Inputs` + `Household(inputs, today)`; `data/inputs.py` fills `Inputs` from the files). `Money` annotated type plus the `*Fields` base pattern, proven on `Account`. The parity harness (`scripts/parity/`, below). Verify the "no digest-time stamp depends on overrides" assumption: holds, as long as the loader resolves offsets the way `api/gql/ledger.py` does. **Output models moved to phase 4**, where each view gets its GraphQL type; adding them now would only be churn. | Done: `pytest` green (853 passed, DB tests skipped); all 12 `data/digested` outputs, `.md` included, byte-identical to the pre-refactor run at a pinned instant |
| **1. Scraped entities** — **done 2026-11-01** (migration 0023) | Tables: `digest_runs`, `accounts`, `credit_cards`, `loans`, `savings_holdings`, `source_dumps` + `source_dump_entities` (per-entity counts, not repeated per source). No `income_sources`: `income` is dead (D8). Digest writes them in the ledger's transaction (`db/ledger.py load`); `db/snapshot_store.py` reads them, and `finance/views/snapshot.totals` over the stored rows equals `snapshot.json`'s totals on real data. `loans.next_payment` waits for phase 2, where forecast reads tables. Served: `Query.snapshot` (rows + computed totals; `incomeSources`, `detectedMonthlySalary`, `generatedAt` dropped) and `dataAsOf`; `Savings.holdingId` + `assignment`; `CreditCard.nextChargeDate`; `SyncSource` `label`, `lastDumpedAt`, `rawFiles`, `latestTxnDate`, `entities`. `SyncSource.connection` skipped: `syncSourceSecrets` already serves the fields. | Done: the resolver equals real `snapshot.json` field by field (`test_snapshot_resolver_equals_snapshot_json`) |
| **2. Inputs** — slice 1 done 2026-11-01 (migration 0024): `offset_rules`, `mortgage_schedule_periods`, `loan_freezes` with `db/input_store.py` (readers prefer the table, the file until `import`); `detect_freeze.py` writes the table; `income` and `subscription` no longer emitted. Slice 2 open: `account_balance_days`, `household_settings`, `loans.next_payment`, the side-file deletions | Tables: `account_balance_days` (new bank entity), `offset_rules`, `mortgage_schedule_periods`, `loan_freezes`, `household_settings`. Importers. `forecast` / `history` / `detect_freeze` / `goals.py` CLI read and write tables. ⚠ Delete `budgets.json`, `goals/goals.json`, `offsets/rules.json`, `mortgage_schedule.json`, `freeze.json` after import. Stop emitting `subscriptions` and `income`. | No builder reads a side file; parity still holds |
| **2b. Off RiseUp** (D8, figure changes on purpose) | **Plan:** import RiseUp's tracking envelopes into `budget_lines` once, only for categories that have no household line. After that, planned = `budget_lines`. **Cycle:** starts on `household_settings.cycle_start_day`. **Past months' expected** (`months`) = the current plan; the RiseUp budget history is no longer read. **Forecast:** built from the ledger instead of envelopes. Income comes from the runway's inferred recurring income, fixed costs from the bill series plus `loans.next_payment` / schedule / freeze, and variable spend from the `budget_lines` plan. Each change gets a user-story test first and a backtest on Aug–Oct 2026 actuals, as was done for the runway card-bill estimate. Remove `riseup` from `refresh-all` and the sync sources; its normalized files stay as the frozen archive. | No code reads `data/riseup/raw`; the backtest error is reported and accepted |
| **3. Typed ledger** | `scraped_transactions` gets one column per `LedgerTransaction` field via the base class; `transaction_auto_offsets`; views rewritten; `api/gql/ledger.py` reads columns, and its hand dataclasses go where a row class exists. ⚠ Drop `record` in a separate, later migration, after a digest has run on the columns. | `test_schema` and parity green; no `record->>` left |
| **4. Views in GraphQL** | `runway`, `pace`, `months`, `cycle`, `monthSummaries`, `history`, `projection`, `horizonAllocation`, `metrics`, goal and target computed fields, the new `Transaction` fields. A parity test for each against the fixture. | Every app-read field in the consumption map is servable |
| **5. App cutover** | Route by route, as above. Delete the overlays. | No `/data/` fetch left in `app/src` |
| **6. Remove JSON** | Digest stops writing `data/digested/*` (keeps only `.lock`). `after_digest` job; `DIGEST_STEPS`, `LedgerRebuildWorkflow`; delete `publish_data`, the `deploy.sh` data loop, the edge-auth `/data` gate and the `sync-status.json` file. The assistant drops `JsonLedger`; `push.py` reads `Household`. `finance.report` replaces the `.md`/`.html` files. Update the root `CLAUDE.md` ("the two things the app reads"), `data/`, `api/`, `db/CLAUDE.md`, `docs/ledger-api.md`, and memory. | `rg "digested/" -g '!docs'` finds nothing but the lock and the CLI |

### Parity harness

D7 is checked by running the whole chain (digest `--no-normalize --no-db`, validate, forecast,
cashflow, goals) at a pinned instant and diffing every `data/digested` output:

```
scripts/parity/run.sh capture /tmp/parity-before   # on the commit before the change
scripts/parity/run.sh check   /tmp/parity-before   # after it; exit 1 on any difference
```

- `pinned.py` runs each script in-process under `time_machine.travel(PIN)` (default
  2026-11-01T12:00+02:00), so `today`, `now()` and `generated_at` are the same in both runs.
- `DATABASE_URL`, `FINANCE_DATA_DIR` and `FINANCE_TENANT_ID` are unset and `FINANCE_NO_DB=1` is
  set: it never reaches the live DB and reads this checkout's `data/` (in a worktree, its copy of
  the real data). It refuses to run where a `.env` exists (the main checkout), since some loaders
  still read `DATABASE_URL` from it.
- It compares the file-backed run. Once a side file is deleted (phase 2), its input only exists in
  the DB, so the harness then needs a seeded throwaway database; that comes with the deletions.
- `PYTHONHASHSEED=0`, because `budgets.summary.variable.categories` follows set order (a
  pre-existing ordering bug, left for its own fix).
- `data/digested/` is restored afterwards, so the pinned outputs never replace the real ones.

From phase 1 on, the same captured directory is the fixture the resolvers' parity tests compare
against.

Phases 1 and 2 are independent and can run in parallel. 2b depends on 2. 3 depends on 0. 4 depends on 1–3 (and on 2b for `cycle`, `months`, `pace` and goals). 5 depends on 4.

## Risks and guards

- **Live DB auto-migrates on connect.**
  - Branch work uses `FINANCE_TEST_DB=finance_test_<branch>` and a dev DB for end-to-end digests.
  - The live DB is migrated only after merge, with your go-ahead.
  - Drops (⚠) are separate migrations, one release later.
- **Human layers are untouchable.** No migration in this plan rewrites `transaction_overrides`,
  tags, offsets, `budget_lines`, goals or `holding_assignments`.
- **API role.**
  - Every new table needs its `GRANT SELECT … TO finance_api` in the same migration. Without it the
    API returns a masked internal error, and nothing at build time catches it.
  - Add a test that `finance_api` can SELECT every tenant table that a resolver reads.
- **Request cost.**
  - One cached `Household` per request computes each view once.
  - Add a timing test: the home screen's query over the real fixture must stay under 300 ms.
  - Move work into SQL only if that fails.
- **`plugin/scripts/`** keeps its own older copies of the pipeline and its own data dir. Out of
  scope: it is untouched, and it keeps writing its own JSON.
- **Multi-tenant.**
  - Every digest write runs under `scope_connection` for the digest's tenant.
  - `sync_status` stays global and master-only, as today. The per-tenant facts live in `source_dumps`.

## Resolved questions (2026-11-01)

1. Validation: no table for now (D9).
2. The `.md` reports become the `finance.report` CLI (D9).
3. The `subscriptions` entity is dropped (D9).
4. RiseUp is deprecated (D8). Its budget inputs are replaced in phase 2b.
