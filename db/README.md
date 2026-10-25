# Transactions database

A local Postgres holds the transaction ledger. It keeps the scraped data and your
manual edits apart, so a re-scrape never loses a category you set by hand.

Postgres runs in Docker Compose (`postgres` service in `docker-compose.yml`). The
ledger code is in `db/ledger.py`, the edit CLI is `db/edit.py`. The tables are SQLModel classes in
`finance/tables.py`; migrations live in `db/migrations/` (Alembic) and run
(`upgrade head`) on every connect.

## Layers

| Object | Layer | Written by | Lifetime |
|---|---|---|---|
| `scraped_transactions` | machine | `ledger.py sync` (from `data/digest.py`) | replaced in full on every digest run |
| `transaction_overrides` | human | `edit.py` | kept forever; sparse (only the fields you changed) |
| `override_audit` | audit | `overrides.py` (CLI and API) | append-only: who changed which field, old and new value |
| `transactions` (view) | read | nothing | scraped rows with overrides applied; excluded rows hidden |
| `orphaned_overrides` (view) | read | nothing | overrides whose transaction no longer exists |
| `transaction_offsets` | human | `offset_store.py` (API) | kept forever: a payback's קיזוז links to expenses (a row with null expense = "offsets nothing") |
| `orphaned_offsets` (view) | read | nothing | offset links whose payback or expense no longer exists |

Rows in both tables are keyed on the ledger dedup key `(date, abs(amount))`, the
same key `data/digest.py` uses. An override field left null falls through to the
scraped value. An override with nothing left in it is deleted.

## Setup

```bash
cp .env.example .env                       # then fill in POSTGRES_PASSWORD and DATABASE_URL
docker compose up -d --wait                # starts postgres (and the Temporal dev server)
poetry install --with sync,dev
```

`DATABASE_URL` must be written out in full in `.env`, for example
`postgresql://finance:<password>@127.0.0.1:5432/finance`. `digest.py` and
`ledger.py` read it literally, without `${...}` expansion. It can also come from
the environment.

Hosted Postgres (Neon, Supabase) is a later option: change `DATABASE_URL` and
nothing else.

## Editing a transaction

A transaction is addressed by its date and amount. The sign is ignored, as in the
dedup key.

```bash
poetry run python db/edit.py show     2026-01-15 123.45
poetry run python db/edit.py category 2026-01-15 123.45 "אלקטרוניקה"
poetry run python db/edit.py note     2026-01-15 123.45 "gift"
poetry run python db/edit.py exclude  2026-01-15 123.45        # hide from the ledger and every total
poetry run python db/edit.py include  2026-01-15 123.45        # undo exclude
poetry run python db/edit.py clear    2026-01-15 123.45 [category|note]   # drop one field, or the whole override
poetry run python db/edit.py list [--orphaned]
```

Every change rebuilds `data/digested/` (digest, validate, forecast, cashflow, goals), so
the JSON the app reads picks it up. Pass `--no-rebuild` to skip the rebuild. Then
push the result to the dashboard with the `sync-data` skill.

Edits go through `db/overrides.py` (get, list, patch, reset, categories, orphaned,
audit). Every change that alters a field writes an `override_audit` row; the CLI's actor is
`cli`, the API's is the signed-in email. A `null` value clears a field, and an override left
empty is pruned.

## The `finance_api` role

Migration `0002` creates `finance_api` (NOLOGIN) for the [ledger API](../api/README.md). It can
SELECT `scraped_transactions` and the views, SELECT/INSERT/UPDATE/DELETE `transaction_overrides`,
and SELECT/INSERT `override_audit`. It cannot truncate, delete or update the scraped layer, or
rewrite the audit log, and it never migrates. To let it log in, put `FINANCE_API_DB_PASSWORD`
in `.env` (URL-safe characters) and run `poetry run python db/ledger.py migrate`. Every
`ledger.connect()` (so every digest) re-applies the password. Roles are cluster-wide, so the
one role serves every database on the server, including `finance_test`.

## How digest uses it

When `DATABASE_URL` is set (in the environment or `.env`), `data/digest.py` builds
the consolidated ledger as before, then pipes it through
`poetry run python db/ledger.py sync`. That imports the rows into
`scraped_transactions` and returns the `transactions` view, in the same order, which
is what gets written to `data/digested/transactions.json`. Cashflow, spending and
the app all read that file, so they see your edits.

`materialize` also attaches each payback's `transaction_offsets` rows as
`manual_offsets`; digest then runs `finance/offsets.py resolve`, where a manual
decision replaces the digest's automatic `auto_offsets` (stored in `record`). See
"Offsets" in CLAUDE.md. Each sync prints a warning per orphaned offset link.

Each row is validated as `finance.models.LedgerTransaction` before it is stored.

## Changing the schema

Edit `finance/tables.py`, then generate and review a migration:

```bash
poetry run alembic -c db/alembic.ini revision --autogenerate -m "add tag to overrides"
```

Views (`transactions`, `orphaned_overrides`) are plain SQL: change them with
`op.execute` in a migration. `db/tests/test_schema.py` fails if the migrated
database and `finance/tables.py` disagree.

- If `DATABASE_URL` is set but the database is down, digest fails loudly. Start
  the container, or run with `--no-db` to skip the database for that run.

## Orphaned overrides

An override is orphaned when its transaction no longer appears in the scraped
data, usually because a bank corrected the date or amount. Orphans are kept, not
deleted, so no edit is lost silently. Each digest run prints a warning for them.

```bash
poetry run python db/edit.py list --orphaned
```

To fix one, either re-create it on the corrected date and amount (then
`clear` the old one), or `clear` it if the transaction is gone for good.

## The .env rule

`docker-compose.yml` reads its values from `.env` with `${...}` interpolation only.
Never add `env_file: .env` to a service. `.env` holds bank credentials, and
`env_file` would copy them into the containers.
