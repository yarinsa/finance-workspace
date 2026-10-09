---
description: View or change financial goals — set emergency-fund / inheritance / retirement targets, add/edit/remove personal goals.
argument-hint: --list | --set-emergency N | --add "desc" --amount N --by YYYY-MM-DD | --edit ID | --remove ID
---

Manage the user-owned goals store via the `goals.py` CLI, then re-digest.

Command: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/goals.py $ARGUMENTS`

Autonomy:

- **`--list`** (and no args) is a read — run it and show targets + goals.
- **Any mutation** (`--set-emergency`, `--set-inheritance`, `--set-retirement`,
  `--add … --amount … --by …` [`--interval`/`--repetitions`/`--rise`], `--edit ID`,
  `--remove ID`) is a **write** — per the finance skill's "always ask" tier, show
  the exact command and its effect and get an explicit yes before running.

The script writes atomically (`.tmp`→rename + one `.bak`), validates input
(amount > 0, ISO date, unique id), and re-digests `goals.json` automatically. After
a change, summarize the new goals state (e.g. via a follow-up `--list`).
