# Ledger API

A small FastAPI service that lets the dashboard edit the human layer of the transactions
database (category, note, hide). The contract, safety model and infra are in
[`docs/ledger-api.md`](../docs/ledger-api.md); this file is how to run it.

```
api/app.py      routes, error shape, body limit      api/rebuild.py  Temporal signal-with-start + status
api/auth.py     origin secret, Cognito JWT, CSRF     api/config.py   env settings, refuses unsafe start
db/overrides.py the override logic (shared with db/edit.py)
```

## Run

In Docker (the normal way). The service has the compose profile `api`, so a plain
`docker compose up -d --wait` does not start an unconfigured API:

```bash
poetry run python db/ledger.py migrate     # migrate, and set the finance_api login password
docker compose up -d api                   # builds api/Dockerfile, binds 127.0.0.1:8787
curl -H "X-Origin-Secret: $FINANCE_API_ORIGIN_SECRET" http://127.0.0.1:8787/api/health
```

Without Docker, for development (needs `poetry install --with api,sync`):

```bash
FINANCE_API_ORIGIN_SECRET=$(openssl rand -hex 24) FINANCE_API_DEV_USER=me@example.com \
API_DATABASE_URL=postgresql://finance_api:<password>@127.0.0.1:5432/finance \
  poetry run uvicorn --factory api.app:create_app --port 8787
```

`FINANCE_API_DEV_USER` skips only the JWT check; the origin secret is still required, a warning
is logged at startup, and `/api/health` reports `"dev": true`. It is never passed by compose.

## Environment

Set in `.env` (see `.env.example`); compose passes exactly these, never `env_file`.

| Variable | Meaning |
|---|---|
| `FINANCE_API_ORIGIN_SECRET` | required; must match CloudFront's `X-Origin-Secret` header |
| `FINANCE_API_COGNITO_REGION`, `_POOL_ID`, `_CLIENT_ID` | the pool whose id tokens are accepted (`iss`, `aud`) |
| `FINANCE_API_ALLOWED_EMAILS` | comma list of emails that may use the API |
| `FINANCE_API_DB_PASSWORD` | password of the Postgres role `finance_api` (compose builds `API_DATABASE_URL` from it) |
| `API_DATABASE_URL` | set by compose; for non-Docker runs, a URL for role `finance_api` |
| `TEMPORAL_ADDRESS` | set to `temporal:7233` by compose |
| `PUSH_VAPID_PUBLIC_KEY` | optional; the Web Push public key served at `GET /api/push/key` (the private key never enters the container) |
| `FINANCE_API_DEV_USER` | development only, see above |

The API refuses to start if the origin secret is missing, or if the Cognito settings and
allowed emails are missing without a dev user.

## Safety model (summary)

1. CloudFront edge-auth and WAF in front; `/api/*` answers 401 JSON instead of redirecting.
2. `X-Origin-Secret` checked with a constant-time compare on every route (health included).
3. The `plangram_session` Cognito id token is verified (RS256 via JWKS, `iss`, `aud`, `exp`,
   `token_use=id`) and the email must be allow-listed. The email is the audit actor. `/api/health`
   needs only the secret, so the container healthcheck needs no session.
4. Writes need `Content-Type: application/json` and `X-Requested-With: finance-app`. Body at most 8 KB;
   category at most 64 characters, note at most 500.
5. The database role `finance_api` can only read the ledger, edit overrides and append to the audit
   log. It cannot truncate or rewrite scraped data. The API never migrates.
6. The container is non-root, read-only, drops all capabilities, and has no AWS or bank credentials.
7. Every change is in `override_audit` (`GET /api/audit`).
8. Fixed endpoints only; no SQL or free-form queries from the client.

An edit never fails because Temporal is down: it is saved first, then the rebuild signal is sent,
and a failed signal is logged. `/api/rebuild` reports `idle` when there is no workflow.

## Live sync status (SSE)

`GET /api/sync/events` streams the `sync_status` table: `retry: 5000`, an `event: snapshot` with
`{"updated_at","sources":{source: entry}}`, then an `event: source` (`{"source","entry"}`) per change, and a
`: ping` comment every 15 s. It closes after 10 minutes (clients reconnect and get a new snapshot), allows at
most 20 concurrent streams (503 beyond), and drops clients that fall 100 events behind. One `LISTEN sync_status`
connection per API process feeds all streams (`api/sse.py`); it reconnects with 1-30 s backoff. Details:
docs/ledger-api.md, "Live sync status". The same connection also `LISTEN`s on `notifications` and the
stream emits `event: notification` with `{"id"}` when an inbox row changes (refetch it over GraphQL).

## Notifications inbox

The home "לטיפול" actions (`data/actions.py`, plus validation failures) are mirrored into the `notifications`
table by `data/cashflow.py` after each digest (`db/inbox.py sync`, best-effort: no database never stops the
digest). Each carries a `category` (PROBLEM, WARNING, REMINDER, SUGGESTION, INFO), a camelCase `type`
(`limitBreach`, `budgetOver`, ...) and a `subject` that picks the GraphQL subtype (`BudgetNotification`, ...;
`api/schema/inbox.graphql`). Ids are the actions' period-stable ids, so a situation is one row across digests.

- **Visible** = not archived, not resolved (the digest stamps `resolved_at` when the action disappears) and not
  snoozed past now; **unread** = visible with no `read_at`. Snoozing also marks the item unread.
- The digest never touches `read_at`, `snoozed_until_at` or `archived_at`; `finance_api` may update only those
  three columns.
- `pushed_at` (Web Push sent it; written by the Mac's `finance/push.py` only) is not exposed over GraphQL and
  `finance_api` cannot update it.
- Queries: `notifications(filter)` (most severe first, then newest), `notificationsUnreadCount(category)`.
  Mutations: `updateNotification` (read, snooze), `archiveNotification` / `unarchiveNotification`, and the bulk
  `markAllNotificationsRead` / `archiveAllNotifications` / `snoozeAllNotifications` (visible items only).
- Inbox mutations are not ledger edits: they do **not** signal `LedgerRebuildWorkflow` (`rebuilds = False` on
  the resolver).

## Kill switch

```bash
docker compose stop api        # the dashboard falls back to read-only
tailscale funnel off           # or cut the public path, leaving the API up locally
```

Undo a bad edit with `GET /api/audit` (old values) plus a patch, or `db/edit.py clear`.

## Tests

```bash
poetry run pytest api/tests    # needs Postgres up; uses the finance_test database only
```

They use a generated RSA key and a fake JWKS (nothing calls AWS), a fake rebuild client, and made-up
transactions. The pool runs `SET ROLE finance_api`, so the tests exercise the real grants.

## Generated GraphQL inputs

`api/schema/*.graphql` is the source of truth. `api/gql/generated/inputs.py` (enums, input
types, and a `<Type><Field>Args` model per field with arguments) is generated from it and
must not be edited by hand. `api/gql/inputs.py` subclasses those models and adds only
behaviour: limits, node-id types, validators, helpers.

Workflow: edit the SDL, run `poetry run python -m api.codegen.generate`, commit both.
`--check` exits 1 if the file is stale; `api/tests/test_codegen.py` runs it, so CI fails on drift.

For the full SDL-first workflow (bindings, resolvers, drift-test fixes) see the `graphql-schema` skill.
