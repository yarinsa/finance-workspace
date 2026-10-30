---
name: schema-change
description: Change the shape of the finance data — add/rename a field on a normalized entity or ledger row, change a Postgres table or view, add a dependency — keeping finance/models.py, finance/tables.py, the Alembic migrations and Poetry in sync. Activate when a normalizer needs a new field, a ValidationError comes out of write_envelope, test_schema.py reports drift, or the user asks to change the DB schema or add a Python package.
---

# Schema change (Pydantic models ⇄ SQLModel tables ⇄ Alembic)

One definition drives everything:

| Layer | File | Enforced by |
|---|---|---|
| Normalized entities (`transactions`, `accounts`, `loans`, …) | `finance/models.py` | `write_envelope` in every `normalize.py` (`extra="forbid"`) |
| Digested ledger row | `finance/models.py` → `LedgerTransaction` | `db/ledger.py load` validates each row |
| Postgres tables | `finance/tables.py` (SQLModel) | `db/tests/test_schema.py` (drift vs migrated DB) |
| Views (`transactions`, `orphaned_overrides`) | SQL in `db/migrations/versions/*` | migrations only |

Always run with `poetry run …` (plain `python3` lacks the deps).

## 1. A normalizer emits a new field

1. Add the field to the entity model in `finance/models.py`, `Optional` with default `None`
   unless every source sets it. Dates use `Date` / `OptDate` (accept ISO, ISO datetime,
   `YYYYMMDD`, `""`→null).
2. If the field reaches the ledger row (digest copies it), add it to `LedgerTransaction` too.
3. Add a real-case test in `data/tests/test_models.py` (actual Hebrew description / amount).
4. `poetry run python data/digest.py` — must not raise `ValidationError`.

A `ValidationError` from `write_envelope` is a finding, not noise: decide whether the
normalizer is wrong (fix it) or the model is too strict (widen it), never drop `extra="forbid"`.

## 2. A column / table changes

1. Edit `finance/tables.py`. Match Postgres types explicitly (`Numeric(12,2)`, `Text`,
   `ARRAY(Text)`, `JSONB`, `TIMESTAMP(timezone=True)` + `server_default`).
2. Generate and **read** the migration (DB must be up: `docker compose up -d --wait`):
   ```bash
   poetry run alembic -c db/alembic.ini revision --autogenerate -m "add tag to overrides"
   ```
   Autogenerate misses views, renames (it emits drop+add — rewrite as `op.alter_column`)
   and server-default changes; fix by hand.
3. If a view selects the changed column, `DROP VIEW` / `CREATE VIEW` it in the same migration
   via `op.execute`.
4. Never truncate or drop `transaction_overrides` — it holds the user's manual edits forever.
   `scraped_transactions` is rebuilt every digest, so it may be recreated freely.
5. `poetry run pytest db/tests` — `test_schema.py` must be green. `db/ledger.py` applies
   `upgrade head` on the next connect; nothing else to run.

## 3. A dependency

`poetry add <pkg>` (pipeline/db) or `poetry add --group sync <pkg>` (Temporal worker only),
commit `pyproject.toml` + `poetry.lock`. No `requirements.txt` files exist any more.

## 4. The GraphQL API exposes it

A model change the app should see also changes `api/schema/*.graphql`: follow the `graphql-schema`
skill (SDL → codegen → bindings → resolvers).

## Done means

`poetry run pytest` passes (the 3 mortgage-freeze tests depend on live data), a digest runs,
and CLAUDE.md's "Python environment and models" section still describes reality.
