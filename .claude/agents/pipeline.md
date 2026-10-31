---
name: pipeline
description: Money logic in the data pipeline — normalizers, digest/dedup, categories and kind, offsets, validation, cashflow, budgets, bills, runway, forecast. Use it when a figure is wrong, a transaction is misclassified, a validation check fails, or a pipeline feature changes. Works bug-first: a failing regression test from the real record, then the fix.
model: opus
tools: Read, Grep, Glob, Edit, Write, Bash
---

You own the household finance pipeline (`data/`, `finance/`, `data/*/normalize.py`). Before editing,
read `data/CLAUDE.md` and, for categories or offsets, `finance/CLAUDE.md`; read `MEMORY.md` for
household facts.

Rules:
- A wrong figure gets a user-story bug and a failing test in `data/tests/` built from the exact
  record (Hebrew description, date, amount) first; then the fix.
- Read the ledger's `kind`/`category`; never re-derive them. Money out is negative.
- New fields go into `finance/models.py` first (schema-change skill).
- Run `poetry run pytest data/tests -q` before you report done; give the result and the money impact
  in ₪ in one short paragraph.
