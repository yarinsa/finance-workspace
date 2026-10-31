---
name: sync-dev
description: Develop and debug the automated sync (Temporal workflows, scrapers/*/scrape.mjs, sync API/GraphQL, /syncs screen). Use for failed syncs (ScrapeFailed, needs_login, rejected) or when changing any of those.
---

# Developing the sync

The pieces (details in `sync/README.md`, `api/README.md`, CLAUDE.md "Automated sync"):

| Piece | Code | Runs as |
|---|---|---|
| Workflow + activities | `sync/workflows.py`, `sync/activities.py`, registry `sync/sources.py` | launchd `me.yarinsa.finance-worker` |
| Headless scrapers | `scrapers/<source>/scrape.mjs` | spawned by the `scrape` / `scrape_login` activities |
| Status, login, OTP, retry | `api/app.py` (REST: login/otp/events/push), `api/schema/sync.graphql` + `SyncSourceResolver` (GraphQL), `api/rebuild.py` (Temporal client) | compose service `api` (profile `api`) |
| UI | `app/src/routes/Syncs.tsx`, `app/src/lib/syncRetry.ts`, `syncStatus.ts` | S3 + CloudFront (`deploy-app`) |

## 1. Debugging a failed source

1. Read the `/syncs` error, or the source's `sync_status` row / `data/sync-status.json`. The `step`
   kept on a failed entry says where it stopped (1 session, 2 scrape, 3 validate, 4 digest, 5 publish).
2. Run the scraper by hand from the main checkout: `node scrapers/<source>/scrape.mjs` (`--check`
   for the session only). **Never** re-run a login the bank refused, and never `--login` an OTP
   source: that sends the human an SMS. Only the human starts an OTP login, from the app.
3. A `--  0B  <file>  <-- NOT JSON, NOT WRITTEN` line from an endpoint the normalizer doesn't
   read is not a failed scrape. List supporting-only endpoints as `OPTIONAL` in the scraper,
   e.g. Harel's `client-claims-by-area` (it answers 200 with an empty body when there are no claims, 2026-10-27).
   Required endpoints stay strict: HTML / non-JSON / non-200 rejects and keeps the previous file.
4. Bugs become tests first (CLAUDE.md "Bugs → tests"): `sync/tests/test_finance_sync.py` drives the
   workflow with `fakes.Fake` on a time-skipping Temporal env.

## 2. The running services load code from the main checkout

The worker and the `api` container run from `/Users/yarinsa/Code/Finance` on `master`, **not**
from a worktree. Editing a worktree changes nothing live until it is merged to master. Then:

```
launchctl kickstart -k gui/$(id -u)/me.yarinsa.finance-worker   # workflow / activities / sources.py / scrapers
docker compose --profile api up -d --build api                  # anything under api/
```

(run from the main checkout). The worker caches code: without the kickstart, runs use the old
logic (e.g. hang in `waiting_for_login`). Ship UI changes with `deploy-app`. A running workflow
keeps the code it started with, so a changed workflow `run` signature needs optional args
(`run(self, sources=None, opts=None)`) so in-flight and scheduled runs still replay.

## 3. API conventions for sync features

- **New app actions are GraphQL mutations, not REST** (the user's rule, 2026-10-27). Use the Linear
  style (`root.graphql`): `entityVerb` name, the target's `id` as its own argument, a
  `{success, entity}` payload. Examples: `syncSourceRetry(id: ID!): SyncSourcePayload!`, `goalUpdate`.
  The REST `/api/sync/*` routes predate this and are only the login/OTP/SSE/push plumbing.
- Schema-first: edit the SDL, run codegen, write the `resolve_<field>` method `bind_all` asks for —
  the full workflow is the `graphql-schema` skill. Resolvers live in `api/gql/resolvers.py`;
  sync resolvers set `rebuilds = False` (starting a sync changes no ledger data). Temporal is
  reached through `info.context["rebuilder"]` (`api/rebuild.Rebuilder`); a failure is a `GraphQLError`.
- `api/tests/test_graphql_schema.py` enforces: new object types are bound or listed in
  `STRUCTURAL` (`api/schema_bindings.py`); every Node type is in its refetchable set; Linear
  mutations are in `LINEAR`; plural fields over Nodes are connections (`paginate`), never lists.
- The API stays powerless: role `finance_api` has only SELECT on `sync_status`. The retry decision
  (`rebuild.resume_point`) is read from that row; the API never runs scrapes itself.
- An OTP source's app-started runs (login **and** retry) use workflow id `finance-sync-login-<source>`,
  because `submit_otp` signals that id. Other retries use `finance-sync-retry-<source>`.

## 4. Retry: continue where it stopped

`syncSourceRetry` maps the failed entry to a resume point: status `failed` with step ≥ 4 resumes at
digest (`FinanceSyncWorkflow([source], {"resume": "digest"})`, which skips preflight and scrape);
any earlier failure or `rejected` re-runs the source (`[source]`; a live session needs no login).
A new resume point needs all three: `resume_point`, the workflow's `opts`, and the `SyncRetryPoint` enum.

## 5. Testing

```
poetry install --with sync,dev
export $(grep '^DATABASE_URL=' /Users/yarinsa/Code/Finance/.env | xargs)   # worktrees have no .env
poetry run pytest api sync                                                # DB tests skip without it
```

App: `cd app && npx tsc --noEmit -p . && npx vitest run` (a worktree has no `node_modules`; symlink the
main checkout's while checking, then remove it). Missing `@/__generated__/*` errors are Relay
artifacts not built in the worktree, not your change. Format with `npx prettier --write`.
