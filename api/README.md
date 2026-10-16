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
FINANCE_API_ORIGIN_SECRET=dev FINANCE_API_DEV_USER=me@example.com \
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
