# Plangram app

Thin React + TS dashboard that renders the finance pipeline's digested outputs —
a reimplementation of the screens documented in `../docs/plangram-prd/` against
**our own** data, not Plangram's backend.

## Run

```bash
cd app
pnpm install
pnpm dev      # http://localhost:5173
pnpm build    # type-check + production build to dist/
```

## How it reads data

There is no backend. Vite aliases `@digested` → `../data/digested`, so the app
imports `cashflow.json`, `snapshot.json`, and `transactions.json` directly. After
re-running `python3 data/digest.py`, the next dev reload (or rebuild) reflects the
new numbers. All shapes are typed in `src/lib/data.ts`.

## Screens (mirrors the 10 PRDs)

| Route | PRD | Status |
|---|---|---|
| `/overview` | 02 | ✅ real (net worth, today cashflow, top metrics) |
| `/cashflow` | 01 | ✅ real (KPIs, net-worth curve, expense breakdown) |
| `/networth` | 06 | ✅ real (assets/liabilities + lifetime curve) |
| `/metrics` | 08 | ✅ real (full metric catalog) |
| `/timeline` | 09 | ⚠️ partial (focal points; monthly waterfall is Phase 2) |
| `/summary` | 03 | ⚠️ status map (journey curve + section completeness) |
| `/recommendations` | 05 | ⚠️ heuristic nudges (no rules engine yet) |
| `/goals` | 04 | ✅ real (4 general cards + personal goals, from `data/goals/`) |
| `/portfolio` | 07 | ⚠️ real (Harel pension + study funds; no fees/yield, no real-estate) |
| `/my-plan` | 10 | ⛔ Plus-gated, not captured |

The ⛔/⚠️ screens render honest "needs input / not captured" notices rather than
fake data — matching each PRD's "what we're missing" section.
