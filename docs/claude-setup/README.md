# Claude setup and usage tracking

The goal is to get more tasks per week from the same plan limit, without losing quality.
We measure from the local session logs with `scripts/claude_usage.py` and compare each
snapshot with the baseline.

```
poetry run python scripts/claude_usage.py --since 2026-11-01 --write 2026-11-07
```

## Baseline (2026-10-31, logs from 2026-09-04)

See `measurements/baseline-2026-10-31.md`.

| Metric | Baseline | Target |
|---|---|---|
| Context at session start (median) | 82,802 tokens | < 40,000 |
| Context per turn (median) | 153,033 tokens | < 90,000 |
| Weighted tokens per session (median) | 1.06M | < 600k |
| Weighted tokens, busiest week (W42) | 68.8M | same work for about half |

Cache reads are about 65% of the weighted total: every turn re-reads the whole context. Two
things shrink that: a smaller fixed start, and shorter sessions.

## What changed (2026-10-31)

| Change | Why |
|---|---|
| Root `CLAUDE.md` cut from 42 KB to 8 KB: purpose, pipeline, the hard rules and an index | It loaded on every turn of every session and subagent |
| Details moved next to their code: `sync/`, `api/`, `db/`, `finance/`, `data/`, `app/` `CLAUDE.md` | Claude loads a directory's file only when it works there |
| `finance-copilot` plugin disabled in this project (`.claude/settings.json`) | Its skills duplicate the project's own skills |
| `israeli-bank` MCP server disabled | The direct scrapers replaced it |
| The eleven `*-refresh` skills merged into one `refresh` skill: a short `SKILL.md` plus `references/<source>.md` and `scripts/<source>/` | Eleven descriptions and bodies loaded into every session; now one description, and a source's details only when needed |
| Descriptions of the other skills cut to one or two sentences | Every description is in the context of every session |
| Machine-global memory pruned: eleven per-skill notes and the superseded June 2026 picture removed; the few facts only they held moved into the `refresh` references | The index loads every session |
| Models for subagents: `design-system`, `backoffice` and `sync-ops` on Sonnet; `pipeline` on Opus | Mechanical work doesn't need the largest model |

## Working habits

1. One task per session. Use `/clear` between tasks; a new task in an old session carries all of the old context.
2. Plan in one session, and implement in a fresh one from the plan.
3. Hand mechanical work (refreshes, screenshots, broad searches) to `sync-ops`, `design-system` or `Explore`.
4. Use `/context` when a session feels heavy, and `/compact` before a long implementation.

## `plugin/` copies

Nothing in the repo (code, tests, scripts, CI, `.claude/settings.json`) loads or imports `plugin/`; the
`finance-copilot` plugin is disabled here and only the docs mention `plugin/scripts/`. It stays as a
standalone distribution with its own copies of the skills and scripts, so it is not kept in step with the
`refresh` skill. Delete it when the plugin is retired.

## Weekly check

A launchd agent runs the measurement every Sunday at 09:17 (Haiku, local, because the script reads `~/.claude`
logs). It makes a `usage/<date>` branch, writes the snapshot, adds the table row and commits; it never pushes
or merges. Log: `~/Library/Logs/finance-usage-check.log`. The plist is copied in `scripts/`.

```
cp scripts/me.yarinsa.finance-usage-check.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/me.yarinsa.finance-usage-check.plist
launchctl kickstart gui/$(id -u)/me.yarinsa.finance-usage-check   # run now
```

## Next steps

- Check `/context` in a new session: the start should be under 40k tokens.
- Take a weekly snapshot and add a row to the table below. The first one is due from 2026-11-07.

| Week | Sessions | Weighted | Per session (median) | Start context | Notes |
|---|---|---|---|---|---|
| Baseline (W36–W44) | 63 | 177.6M | 1.06M | 82.8k | before the setup |
