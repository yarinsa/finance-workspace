# Plangram app

Thin React + TS dashboard that renders the finance pipeline's digested outputs —
a reimplementation of the screens documented in `../docs/plangram-prd/` against
**our own** data, not Plangram's backend.

## Stack

Vite + React 19 + TypeScript, **Tailwind CSS v4** (`@tailwindcss/vite`, no config
file; `@import "tailwindcss"` in `src/index.css`) and **shadcn/ui** (radix, nova
preset, neutral, RTL, dark by default via `class="dark"` on `<html>`).

Add a component: `pnpm dlx shadcn@latest add <name>` — lands in
`src/components/ui/`. Config is `components.json`; import via `@/components/ui/...`.
Project-specific shared pieces (legacy `Card`, `Kpi`, ...) live in
`src/components/common.tsx`.

Legacy hand-rolled styles remain in `src/styles.css` (imported after Tailwind).
Their CSS variables are namespaced `--lg-*` so they don't clash with shadcn tokens.
The app shell (`App.tsx`) uses the shadcn Sidebar; routes are not yet restyled.

## Run

```bash
cd app
pnpm install
pnpm dev      # http://localhost:5173
pnpm build    # type-check + production build to dist/
```

## How it reads data

There is no backend, and **no data in the bundle**. The app fetches
`/data/{cashflow,snapshot,transactions,goals}.json` at runtime (top-level await in
`src/lib/data.ts`; shapes typed there). Locally, `vite.config.ts` serves `/data/*`
straight from `../data/digested`, so after `python3 data/digest.py` a reload shows
the new numbers.

## Deploy

Code and data ship separately:

- **App bundle** — automatic. Merging to `master` (anything under `app/`) runs
  `.github/workflows/deploy-app.yml`, which assumes an OIDC role
  (`infra/github-deploy.tf`) and runs `infra/deploy.sh --app-only`. CI never sees
  financial data; the role is denied access to `data/*` in the bucket.
- **Data** — from your machine after a refresh: `infra/deploy.sh --data-only`.
- Both at once (manual): `infra/deploy.sh`.

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
