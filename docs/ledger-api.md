# Ledger API — editing transactions from the dashboard

The dashboard (https://my-finance.yarinsa.me, static on S3 + CloudFront, every
request gated by the Cognito Lambda@Edge check) gets a small write API for the
human layer of the transactions database (`transaction_overrides`). The database
stays on the Mac; nothing new is hosted.

```
browser ─► CloudFront my-finance.yarinsa.me   (WAF rate limit + edge-auth on every path)
            ├─ /*      → S3            static app + /data/*.json  (read path, unchanged)
            └─ /api/*  → Tailscale Funnel https://<mac>.<tailnet>.ts.net
                          → 127.0.0.1:8787  finance-api (Docker Compose)
                              ├─ Postgres  as role finance_api (overrides only)
                              └─ Temporal  signal-with-start LedgerRebuildWorkflow
                                            → host worker: digest chain → deploy --data-only
```

## Cost

$0 fixed. Tailscale Funnel is free; Lambda@Edge + CloudFront for a handful of API
calls a day is well inside free tier. Publishes are debounced (one per burst of
edits), so CloudFront invalidations stay far below the 1,000/month free quota.

## Safety model

1. **Edge** — `/api/*` runs the same edge-auth viewer-request function. For `/api/*`
   an unauthenticated request gets `401 {"error":"unauthenticated"}` instead of the
   302 to the login page. WAF rate-limits as for every path.
2. **Origin secret** — CloudFront adds `X-Origin-Secret` (Terraform
   `random_password`, copied to `.env` as `FINANCE_API_ORIGIN_SECRET`). The API
   rejects anything without it (constant-time compare), so the public Funnel URL is
   useless on its own.
3. **JWT re-check** — the API verifies the `plangram_session` Cognito id token
   (RS256, JWKS, `iss`, `aud`=client id, `exp`, `token_use=id`) and requires the
   email to be in `FINANCE_API_ALLOWED_EMAILS`. The verified email is the audit actor.
4. **CSRF** — same origin, SameSite=Lax cookie, writes require
   `Content-Type: application/json` and `X-Requested-With: finance-app`.
5. **Least privilege** — the API connects as Postgres role `finance_api`: SELECT on
   `scraped_transactions` and the views, SELECT/INSERT/UPDATE/DELETE on
   `transaction_overrides`, INSERT/SELECT on `override_audit`. It never migrates.
6. **Isolation** — the API container is non-root, read-only filesystem, gets only
   `API_DATABASE_URL`, `TEMPORAL_ADDRESS`, `FINANCE_API_*` env (never `env_file: .env`),
   binds `127.0.0.1:8787`. It has no AWS or bank credentials; publishing happens in
   the host worker.
7. **Audit + undo** — every change writes an `override_audit` row (actor, field, old,
   new). Kill switch: `docker compose stop api` or `tailscale funnel off`; the UI
   falls back to read-only.
8. **No generic query surface** — fixed endpoints, Pydantic-validated bodies
   (category ≤ 64 chars, note ≤ 500), body size ≤ 8 KB (16 KB for GraphQL), no SQL from the client.

## Contract (all pieces build against this)

Key: a transaction is `(date, abs_amount)` — ISO date and the absolute amount as a
2-decimal string, e.g. `2026-01-15` / `123.45`. UI computes it from a ledger row as
`Math.abs(amount).toFixed(2)`.

`Row` (JSON):
```json
{"date":"2026-01-15","abs_amount":"123.45","amount":-123.45,"description":"…",
 "category":"…","scraped_category":"…","note":null,"excluded":false,
 "overridden":true,"origin":"cal","sources":["cal","riseup"]}
```

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/api/health` | — | `{"ok":true,"db":true,"temporal":true}` |
| GET | `/api/transactions` | `?from=&to=` (ISO dates), `&excluded=include\|only` (default: hide) | `{"transactions":[Row]}` |
| GET | `/api/transactions/{date}/{abs_amount}` | — | `Row` or 404 |
| PATCH | `/api/transactions/{date}/{abs_amount}` | any of `{"category":str\|null,"note":str\|null,"excluded":bool,"horizon":"current\|near\|future"\|null,"goal_id":int\|null}`; `null` clears that field (unknown `goal_id` → 422) | `Row` (empty overrides are pruned) |
| DELETE | `/api/transactions/{date}/{abs_amount}/override` | — | `Row` back to scraped values |
| GET | `/api/categories` | — | `{"categories":[str]}` (distinct, scraped + overrides, sorted) |
| PUT | `/api/transactions/{date}/{abs_amount}/tags` | `{"tags":[str]}` (≤20, replaces the set) | `Row` |
| GET | `/api/tags` | — | `{"tags":[{id,name,color,count}]}` |
| GET | `/api/horizons` | — | `{"horizons":[{id,key,name,target_pct,position}]}` (fixed, seeded by migration 0006) |
| GET | `/api/goals` | — | `{"goals":[Goal]}` — `{id,slug,description,amount,start_date,end_date,interval,repetitions,rise,from_asset_id,horizon,transactions}` |
| POST | `/api/goals` | `{"description","amount",…, "horizon"?}` | `Goal` |
| PATCH | `/api/goals/{id}` | any goal field; `"horizon":null` unassigns | `Goal` or 404 |
| DELETE | `/api/goals/{id}` | — | `{"deleted":id}`; its transactions are unassigned |
| GET | `/api/overrides/orphaned` | — | `{"overrides":[{date,abs_amount,category,note,excluded}]}` |
| GET | `/api/audit` | `?limit=50` | `{"entries":[{at,actor,date,abs_amount,field,old,new}]}` |
| GET | `/api/rebuild` | — | `{"state":"idle\|pending\|running","last_published_at":iso\|null,"last_error":str\|null}` |

Errors: `{"error":"<code>","message":"…"}` with 400/401/403/404/413/422/503.
Any successful write (POST/PUT/PATCH/DELETE) signals a rebuild.

### GraphQL (schema-first, replacing the REST routes)

The contract is the SDL in **`api/schema/*.graphql`**. Write the schema change first,
then the code. It follows Relay: `Node` + `Query.node(id)` for refetching, cursor
connections (`edges`/`node`/`cursor`/`pageInfo`) for every list, and mutations
that take one `input` and echo `clientMutationId`.

- **IDs** are opaque global IDs (`base64("Transaction:2026-01-15:123.45")`). A
  transaction's ID still wraps the `(date, abs_amount)` key.
- **Cursors** are keyset cursors over that key, so a page doesn't shift when an edit lands.
- **`Money`** is a 2-decimal string with the sign (money out is negative), never a Float.
- **Expense / income** is one `Transaction` type with `direction`; `Query.expenses` and
  `Query.incomes` are the filtered connections.
- **`raw`** holds the scraped values before any override (REST's `scraped_*` fields).
- **Relations:** the "one" side of a 1:M relation is the object itself
  (`Transaction.category: Category`). Anything plural over a `Node` is a paginated
  connection, never a list: that covers the "many" side of 1:M, every M:M, and the root
  `merchants`/`categories`/`tags`. Every connection has `totalCount`.
- **Edge totals:** each `MerchantEdge`/`CategoryEdge`/`TagEdge` carries
  `totals { count sum }`, scoped to the edge. Under `Merchant.categories` it is that
  merchant's share of the category; at the root it is the whole group. The same
  connections take `dateRange` and `orderBy: GroupOrder` (default `TOTAL_DESC`).
  New grouped resources follow this pattern.
- **`Merchant`** is derived from the description (`data/spending.py` `merchant_name`),
  not stored.

**Serving** (`POST /api/graphql`, `api/gql/`):

- **Resolvers:** one class per entity in `resolvers.py`. `NodeResolver` covers global IDs
  and `Query.node`. `GroupResolver` covers merchant, category and tag: `transactions`,
  the root connection with edge totals, and an M:M field to every other group entity.
  A new grouped resource is one subclass in `ENTITIES` plus its SDL.
- **Arguments:** each resolver validates its arguments through Pydantic (`inputs.py`,
  `relay.py`), so IDs and cursors are decoded and `first`/`last` capped at 200.
- **Loading:** a request loads the whole effective ledger once (`ledger.py`) and filters
  in memory. That is fine for a few thousand rows, and it's the only way to group by
  merchant, which is derived in Python (`finance/merchants.py`).
- **Limits:** a depth limit of 14 and an 8,000-character query. Introspection is on only
  with `FINANCE_API_DEV_USER`. Resolver crashes reach the client as `internal error`.
- **Not served yet:** mutations return 400 until step 3, and `snapshot` returns an error
  because the API container has no `data/` mount.

Each object type is bound to its Pydantic model in `api/schema_bindings.py`. Then
`api/tests/test_graphql_schema.py` fails when the SDL and the models drift:

- an SDL field has no model field;
- a model field is neither exposed nor `hidden`;
- a non-null SDL field sits on an optional model field;
- an enum disagrees with its `Literal` or CHECK constraint.

The same safety rules apply: same edge auth and origin secret, the CSRF headers on any
request that carries a mutation, POST only, depth and `first` limits, and introspection
off in production. The client compiles against the committed SDL.

### Rebuild workflow (Temporal)

- Type `LedgerRebuildWorkflow`, id **`ledger-rebuild`**, task queue `finance-sync`,
  signal **`edited`** (no args), query **`status`** → the `/api/rebuild` shape.
- Started with signal-with-start; ID reuse allowed. Debounce: waits until 20 s pass
  with no new `edited` signal, then runs the existing `digest` (DIGEST_STEPS with
  `digest.py --no-normalize`) and `publish_data` activities. Signals during a run
  queue one more pass. Idles out after 10 min without signals (or continues-as-new).
- Digest runs (this workflow and FinanceSyncWorkflow) take a file lock
  (`data/digested/.lock`) so they never overlap.

### Schema changes (Alembic `0002`)

- `override_audit(id bigserial pk, at timestamptz default now(), actor text not null,
  txn_date date, abs_amount numeric(12,2), field text, old jsonb, new jsonb)` in
  `finance/tables.py`.
- Role `finance_api` (NOLOGIN in the migration, grants as above). `db/ledger.py`
  sets `LOGIN PASSWORD` from `FINANCE_API_DB_PASSWORD` when present, after migrating.
- `transactions` view unchanged; the API reads excluded rows from
  `scraped_transactions LEFT JOIN transaction_overrides`.

## Infra

- CloudFront: second origin = Funnel hostname (`var.api_origin_domain`, HTTPS only,
  TLSv1.2), ordered behavior `/api/*`: all methods, CachingDisabled,
  AllViewerExceptHostHeader origin request policy, edge-auth viewer-request,
  `X-Origin-Secret` custom header. The behavior and origin exist only when
  `api_origin_domain` is set.
- SPA routing moves from distribution-wide `custom_error_response` (which would turn
  API 403/404s into `index.html`) into the edge-auth Lambda: after auth passes, any
  non-`/api/` URI whose last segment has no `.` is rewritten to `/index.html`. (A
  CloudFront Function would have been the obvious choice, but a behavior cannot have a
  CloudFront Function *and* Lambda@Edge on viewer-request, and the Lambda is needed
  there for auth.) Files with an extension (`/data/*.json`, `/assets/*`) are untouched,
  so a genuinely missing asset is still S3's 403. Tests: `node --test infra/edge-auth/edge-auth.test.js`.
- `infra/tunnel.sh` sets up `tailscale funnel --bg --https=443 --set-path=/api
  http://127.0.0.1:8787/api` (the mount prefix is stripped, hence `/api` in the target)
  and prints the hostname to put in `terraform.tfvars`. `--off` turns it off. The user
  installs Tailscale, logs in, and allows Funnel for the machine via `nodeAttrs` in the
  tailnet policy; no agent authenticates.
- `random_password.api_origin_secret` exists only while `api_origin_domain` is set
  (re-enabling after a rollback rotates it); read it with
  `terraform output -raw api_origin_secret`.

### Rollout steps

1. Install Tailscale, log in, and enable Funnel for this machine in the tailnet policy (you).
2. `infra/tunnel.sh` - prints the Funnel hostname.
3. Set `api_origin_domain = "<host>"` in `infra/terraform.tfvars`, then `terraform apply`.
   (The first apply also swaps the SPA error-response routing for the Lambda rewrite;
   with the variable empty that is the only change.)
4. Put the secret in `.env`: `FINANCE_API_ORIGIN_SECRET=$(terraform output -raw api_origin_secret)`.
5. `docker compose up -d api`; check `https://my-finance.yarinsa.me/api/health` while signed in.

### Rollback

- Quick kill switch: `docker compose stop api` and/or `infra/tunnel.sh --off`. The UI goes read-only.
- Full: unset `api_origin_domain` (or set it to `""`) and `terraform apply` - removes the
  origin, the `/api/*` behavior and the secret. Then `tailscale funnel reset` to clear
  all Funnel config on the node.

## UI

- `app/src/lib/api.ts` — typed client for the table above; `credentials:"same-origin"`,
  the CSRF header, 401 → reload (edge sends to login), network error / 502 / 503 / 504
  → `offline`.
- `useLedgerApi()` — reachability (polls `/api/health`), rebuild status.
- Transaction row → edit sheet (category picker from `/api/categories` + free text,
  note, hide/unhide, reset). Optimistic overlay on the static JSON until the rebuild
  publishes, then refetch `/data/*.json`. Offline: the sheet shows read-only with
  "עריכה זמינה כשהמחשב הביתי פועל".
- Vite dev: `/api` proxied to `127.0.0.1:8787`, injecting `X-Origin-Secret` from `.env`.
  The API's dev bypass (`FINANCE_API_DEV_USER`) skips only the JWT check (the origin
  secret is still required), logs a warning at startup, and `/api/health` reports
  `"dev":true` so the UI shows a banner. It is never set in compose.
