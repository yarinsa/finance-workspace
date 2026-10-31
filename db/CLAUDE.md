# Transactions database

Loaded when working under db/. Project overview: the root CLAUDE.md.

### Transactions database (Postgres)

A local Postgres (Docker Compose) holds the ledger in two layers: `scraped_transactions`
(replaced on every digest run) and `transaction_overrides` (manual category/note/excluded
edits, kept forever), read through the `transactions` view. When `DATABASE_URL` is set,
`data/digest.py` pipes the ledger through `db/ledger.py sync`, so `transactions.json`
reflects edits. Edit with `db/edit.py` (it rebuilds `data/digested/`); push with `sync-data`.
Setup, the orphaned-override rule and the `.env` rule are in **db/README.md**.
Override logic lives in `db/overrides.py` (shared by `edit.py` and the API); every change
writes an `override_audit` row (actor, field, old, new).

