---
name: add-db-entity
description: Add a new entity (lookup/reference table) to the transactions Postgres DB and link the ledger to it by foreign key instead of free text — SQLModel table with Relationships, hand-written Alembic migration (backfill, views, finance_api grants), seeding on import in db/ledger.py, the override layer, tests, and showing it in the dashboard. Activate when the user wants a new table/entity in the DB (categories, merchants, tags, accounts…), to replace a free-text column with a reference, or to "normalize" a ledger field into its own table.
---

# Add a DB entity (lookup table + FK from the ledger)

Worked example: `categories` (migration `db/migrations/versions/0004_categories.py`).
Read it first — every step below is in it. For plain column changes use `schema-change`.

## 1. Model it — `finance/tables.py`

- New `SQLModel, table=True` class with `id: int | None = Field(default=None, primary_key=True)`,
  a unique natural key (`name`), a `source` with a `CheckConstraint` (where the row came from:
  e.g. `riseup` | `user`), and `created_at` via `_now()`.
- FK columns via a helper returning
  `Column(Integer, ForeignKey("<table>.id", ondelete="SET NULL"), nullable=True, index=True)`
  so a deleted entity never deletes ledger rows.
- **Always link with ORM `Relationship`s on both sides** (`back_populates`):
  `scraped: list["ScrapedTransaction"] = Relationship(back_populates="<x>_ref")` on the entity,
  `<x>_ref: Entity | None = Relationship(back_populates=...)` on each referencing table.
  Name the relationship `<x>_ref` so it doesn't clash with a legacy text column.
- Keep the scraped raw text column (`scraped_transactions.<x>`) — it's the source's label;
  the FK is the assignment. On `transaction_overrides`, replace the text column with `<x>_id`.

## 2. Migration — hand-written, not autogenerate-only

Views (`transactions`, `orphaned_overrides`) are plain SQL and depend on the columns, so:

1. `CREATE TABLE` (names must match SQLModel defaults: `ix_<table>_<col>` indexes,
   `<table>_<col>_fkey` FKs) and `ADD COLUMN <x>_id … REFERENCES … ON DELETE SET NULL`.
2. **Backfill** from existing data (seed the entity, `UPDATE … SET <x>_id` by name) *before* dropping text.
3. `DROP VIEW orphaned_overrides; DROP VIEW transactions;` → drop the old text column →
   recreate both views joining the entity. The view must expose the **name** (so readers don't change)
   and put it in `record` with `(s.record - '<x>') || jsonb_strip_nulls(jsonb_build_object('<x>', e.name, '<x>_id', e.id, …))`
   so free text never leaks through. New view columns go last.
4. Re-grant: `SELECT` on the views; `SELECT, INSERT` on the entity + `USAGE` on its `_id_seq`
   to `finance_api` only if the API may create rows (least privilege — see CLAUDE.md "Ledger API").
5. A real `downgrade()` that restores the text column from the names.

## 3. Wire the code

- `finance/models.py` → add `<x>_id: int | None = None` to `LedgerTransaction` (`extra="forbid"`).
- `db/ledger.py load()` → seed the entity from the ledger in the same transaction
  (`INSERT … ON CONFLICT (name) DO NOTHING`), get `{name: id}`, write `<x>_id` per row.
  Decide which source is authoritative (categories: only rows with `riseup` in `sources`).
- `db/overrides.py` → `ROW_SELECT`/`get_override` join the entity; `patch` resolves name → id
  (helper that inserts a `user` row if new); `_prune` checks `<x>_id IS NULL`; listing reads the table.
  The API contract stays name-based. Audit rows keep names (readable).
- `db/edit.py` → its own SQL joins too (`override()`, `list_overrides()`).

## 4. Tests

- Add the table to `TRUNCATE` in `db/tests/conftest.py` and `api/tests/conftest.py` (rows persist otherwise).
- Round-trip tests compare against input: strip the view-added `<x>_id` (`plain()` in `test_ledger.py`).
- New cases: seeded + assigned by id; a value from a non-authoritative source is *not* assigned;
  a manual value is added as `user`. `db/tests/test_schema.py` must pass (no model/DB drift).
- `poetry run pytest` (pre-existing failures: check with `git stash` before blaming the change).

## 5. Apply and show it

- `poetry run python db/ledger.py migrate` then `poetry run python data/digest.py --no-normalize`;
  check how many rows got an id.
- Dashboard: add `<x>_id?` to the TS types in `app/src/lib/data.ts`; a small shared component
  (see `app/src/components/CategoryTag.tsx`) rendered in every transaction row
  (`RecentTransactions`, `routes/Spending.tsx`, `routes/Horizons.tsx`); pass the field through any
  Python block that feeds a list (e.g. `data/horizons.py` `top`). `npx tsc --noEmit`, `npx vitest run`,
  then verify with the `app` preview.
- Restart the API container if its SQL changed (`docker compose up -d --build api`). Publishing data
  (`sync-data`) and deploying (`deploy-app`) are separate, user-approved steps.

## Worked examples beyond categories

- `0005_tags.py` — many-to-many by ledger key (`transaction_tags`), ORM module `db/tags.py`.
- `0006_horizons_goals.py` — a fixed seeded list (`horizons`, addressed by `key`; API stays
  key-based) plus a user entity (`goals`, ORM module `db/goal_store.py`) that itself points at
  it, and a second FK on overrides (`goal_id`). Name a db/ module so it never shadows a
  `data/` script (`goal_store`, not `goals`): pytest puts both dirs on the path.

- `0007_transaction_offsets.py` — a link **between two ledger keys** (payback → expense,
  ORM module `db/offset_store.py`), with a nullable "decision" row (no expense = "offsets
  nothing"). It leaves the `transactions` view alone: `db/ledger.py materialize` attaches
  the rows in Python, and the API reads the table itself. Use this shape when a human
  decision relates two transactions rather than labelling one.

## Gotcha: `ledger.orm_session` on a connection with pending writes

The session shares the psycopg connection and its transaction. SQLAlchemy rolls back on
first connect and on session close, which would silently drop uncommitted psycopg writes
made earlier on `conn`; `orm_session` disables that rollback (the connection's owner rolls
back on error). Don't re-enable it.
