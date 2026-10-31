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


## The two things the app reads

- **`data/digested/transactions.json`**: the unified ledger, deduped on `(date, abs(amount))`, with `sources: [...]` and a `summary` block. Use it for spending, category and cashflow questions.
- **`data/digested/snapshot.json` / `snapshot.md`**: balances, card debt, loans, savings and totals. Use it for net-worth and debt questions.

## Rules that apply everywhere

- **The user logs in.** Never type credentials, OTPs or card numbers, never read them from Keychain or Messages, and never authenticate a Chrome session.
- **Never overwrite a good dump with error stubs.** Check that the session is live before writing; gate with `data/validate.py dump <source>`.
- **Discount order:** the three Discount apps share one login, and the business app's session blocks mortgage. See sync/CLAUDE.md.
- **Money out is negative.** Savings are assets, never transactions. Read the ledger's `kind`/`category`; never re-derive them.
- **GraphQL is schema-first** (`api/schema/*.graphql` → codegen). Never edit `generated/`.
- **Never apply Terraform or a live migration** without the user's go-ahead on a shown plan.
- **The user does outward steps** (Tailscale, Funnel, `terraform apply`, secrets into `.env`).
- **Ask for `BIRTH_DATE`** if it's missing or wrong; never guess it.

## Where the details live (read the one your task touches)

| Topic | File |
|---|---|
| Sync (Temporal), headless scrapers, refresh-all, freshness | `sync/CLAUDE.md` · skill `sync-dev` |
| Ledger API, auth layers, secrets vault, inbox, tenants | `api/CLAUDE.md` · `docs/ledger-api.md` · `docs/tenancy.md` · `docs/secrets-vault.md` · `docs/passwordless-auth.md` (sign-in, invites) |
| Postgres layers and overrides | `db/CLAUDE.md` · `db/README.md` |
| Categories, kind, offsets (קיזוז) | `finance/CLAUDE.md` |
| Validation, forecast, runway, budgets, history, projection, dedup, sources, saving-money method | `data/CLAUDE.md` |
| Dashboard UI, `/monthly` | `app/CLAUDE.md` · the `design-system` agent |
| Household facts (loans, freeze, birth date) | `MEMORY.md` (gitignored) |
| Claude setup and usage tracking | `docs/claude-setup/README.md` |

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
