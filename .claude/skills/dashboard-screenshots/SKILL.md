---
name: dashboard-screenshots
description: Run the Plangram dashboard (app/) and screenshot every route at mobile (390x844 @2x, dark) or desktop size. Use when the user wants to see the app or how a UI change looks.
---

# Dashboard screenshots

Screenshots contain real financial figures. They go to `.claude/screenshots/` (gitignored) and must never be committed.

## One command

```
node .claude/skills/dashboard-screenshots/scripts/screenshot.mjs --full-page
```

Flags: `--routes /overview,/cashflow` (default: every route parsed from `app/src/routes/index.tsx`), `--desktop` (adds 1440x900), `--no-mobile` (desktop only), `--full-page`, `--port 5173`, `--keep-server`, `--light` (light colour scheme; files get a `-light` suffix).

Output: `.claude/screenshots/<timestamp>/<viewport>-<route>.png` (e.g. `mobile-my-plan.png`). The script prints the directory, the file list, and console/page errors per route. Exit code is 1 if any route failed or logged errors.

## What the script does

1. Server: reuses a dev server already answering on :5173; otherwise runs `pnpm dev --strictPort` in `app/` in the background (log: `.claude/screenshots/dev-server.log`), polls until ready (60s max), and runs `pnpm install` first if `app/node_modules` is missing. A server it started is stopped at the end unless `--keep-server`; a pre-existing one is never killed.
2. Visits each route, waits for network idle plus 1.5s so recharts finishes animating, screenshots, and records console errors, page errors and failed requests.

## Prerequisites (one time per checkout)

- Data symlink (the dev/preview server serves `/data/*` from `data/digested`, gitignored):
  `ln -s /Users/yarinsa/Code/Finance/data/digested data/digested` (from the repo/worktree root). Never commit it.
- Playwright lives in this skill dir, not `app/`: `cd .claude/skills/dashboard-screenshots && npm install` (node_modules is gitignored). No browser download needed: if Playwright's pinned Chromium is absent, the script falls back to any `chromium-*` in `~/Library/Caches/ms-playwright`. Otherwise run `npx playwright install chromium` in the skill dir.

## Manual server control

- Start: `cd app && pnpm dev` (background it), check `curl -sf localhost:5173`.
- Stop: kill the process listening on 5173 (`lsof -ti :5173 | xargs kill`).

## Sending to the user

Read a couple of PNGs to sanity check before sending. Mobile viewport shows the sidebar as an off-canvas/top bar depending on the app's current CSS; if `.claude/screenshots/*/` shows errors, report them rather than hiding them.
