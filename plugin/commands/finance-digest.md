---
description: Rebuild all digested finance outputs from the normalized data (no bank login).
argument-hint: [--no-normalize]
---

Rebuild the digested finance data. This does **not** log into any bank — it only
re-runs the local pipeline over already-scraped data.

Steps (run from the plugin, against the resolved data dir):

1. `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/digest.py $ARGUMENTS`
   — runs each source's `normalize.py` (unless `--no-normalize`), then combines the
   normalized layer into `transactions.json` + `snapshot.json`, and auto-builds
   `cashflow.json`.
2. `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/forecast.py` — next-3-month forecast.
3. `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/goals.py` — goals digest.

Report what changed (freshness, any totals that moved). This is a read-only-over-
scraped-data rebuild; safe to run anytime. If a source's raw data is stale, suggest
`/finance-refresh <source>` first.
