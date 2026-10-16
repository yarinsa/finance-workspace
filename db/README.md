# Transactions database

A local Postgres holds the transaction ledger. It keeps the scraped data and your
manual edits apart, so a re-scrape never loses a category you set by hand.

Postgres runs in Docker Compose (`postgres` service in `docker-compose.yml`). The
ledger code is in `db/ledger.py`, the edit CLI is `db/edit.py`, and the schema is
`db/schema.sql` (applied idempotently on every connect).

## Layers

| Object | Layer | Written by | Lifetime |
|---|---|---|---|
| `scraped_transactions` | machine | `ledger.py sync` (from `data/digest.py`) | replaced in full on every digest run |
| `transaction_overrides` | human | `edit.py` | kept forever; sparse (only the fields you changed) |
| `transactions` (view) | read | nothing | scraped rows with overrides applied; excluded rows hidden |
| `orphaned_overrides` (view) | read | nothing | overrides whose transaction no longer exists |

Rows in both tables are keyed on the ledger dedup key `(date, abs(amount))`, the
same key `data/digest.py` uses. An override field left null falls through to the
scraped value. An override with nothing left in it is deleted.

## Setup

```bash
cp .env.example .env                       # then fill in POSTGRES_PASSWORD and DATABASE_URL
docker compose up -d --wait                # starts postgres (and the Temporal dev server)
.venv/bin/pip install -r db/requirements.txt
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
.venv/bin/python db/edit.py show     2026-01-15 123.45
.venv/bin/python db/edit.py category 2026-01-15 123.45 "אלקטרוניקה"
.venv/bin/python db/edit.py note     2026-01-15 123.45 "gift"
.venv/bin/python db/edit.py exclude  2026-01-15 123.45        # hide from the ledger and every total
.venv/bin/python db/edit.py include  2026-01-15 123.45        # undo exclude
.venv/bin/python db/edit.py clear    2026-01-15 123.45 [category|note]   # drop one field, or the whole override
.venv/bin/python db/edit.py list [--orphaned]
```

Every change rebuilds `data/digested/` (digest, forecast, cashflow, goals), so
the JSON the app reads picks it up. Pass `--no-rebuild` to skip the rebuild. Then
push the result to the dashboard with the `sync-data` skill.

## How digest uses it

When `DATABASE_URL` is set (in the environment or `.env`), `data/digest.py` builds
the consolidated ledger as before, then pipes it through
`.venv/bin/python db/ledger.py sync`. That imports the rows into
`scraped_transactions` and returns the `transactions` view, in the same order, which
is what gets written to `data/digested/transactions.json`. Cashflow, spending and
the app all read that file, so they see your edits.

`data/digest.py` itself stays stdlib-only. Only `db/ledger.py` needs `psycopg`.

- If `DATABASE_URL` is set but the database is down, digest fails loudly. Start
  the container, or run with `--no-db` to skip the database for that run.

## Orphaned overrides

An override is orphaned when its transaction no longer appears in the scraped
data, usually because a bank corrected the date or amount. Orphans are kept, not
deleted, so no edit is lost silently. Each digest run prints a warning for them.

```bash
.venv/bin/python db/edit.py list --orphaned
```

To fix one, either re-create it on the corrected date and amount (then
`clear` the old one), or `clear` it if the transaction is gone for good.

## The .env rule

`docker-compose.yml` reads its values from `.env` with `${...}` interpolation only.
Never add `env_file: .env` to a service. `.env` holds bank credentials, and
`env_file` would copy them into the containers.
