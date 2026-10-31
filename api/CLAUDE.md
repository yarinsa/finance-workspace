# Ledger API, inbox and tenants

Loaded when working under api/. Project overview: the root CLAUDE.md.

### Ledger API (editing from the dashboard)

The dashboard edits transactions through `api/` (FastAPI, compose service `api`, profile
`api`, `127.0.0.1:8787`), reached as `/api/*` on the same CloudFront domain via a Tailscale
Funnel to the Mac. Design, contract and rollout: **docs/ledger-api.md**; run/env: `api/README.md`.
Rules that keep it cheap and safe — keep them when changing anything here:

- **Every layer checks.** Edge-auth (Cognito) gates `/api/*` (401 JSON, not a redirect);
  the API requires CloudFront's `X-Origin-Secret` (≥32 chars), re-verifies the
  `plangram_session` id token, allow-lists emails, and needs the CSRF headers on writes.
- **The internet-facing process has no power.** The API container is non-root, read-only,
  gets only explicit env (never `env_file: .env`), and connects as Postgres role
  `finance_api` (overrides + audit only, never migrates). It holds no AWS or bank creds.
- **Publishing stays on the Mac.** An edit signals `LedgerRebuildWorkflow` (id
  `ledger-rebuild`, debounced 20 s) in the host worker, which runs the digest chain with
  `--no-normalize` and `publish_data`. Digests take `data/digested/.lock`.
- **Mac off = read-only.** The UI falls back to the static JSON and disables editing.
  Kill switch: `docker compose stop api` or `infra/tunnel.sh --off`.
- **GraphQL is schema-first.** `api/schema/*.graphql` is the source of truth; Python inputs and
  resolver contracts are generated (`poetry run python -m api.codegen.generate`), resolvers bind
  by name and the API refuses to start with one missing; the app's types come from
  `relay-compiler` (`pnpm codegen`). Never code-first, never edit `generated/`. Workflow: the
  `graphql-schema` skill; open gaps: issue #60.
- **The user does the outward steps**: installing/logging in to Tailscale, enabling Funnel,
  `terraform apply`, copying the secret into `.env`. SPA routing lives in the edge-auth
  Lambda (not CloudFront error responses, which would swallow API 403/404s).

### Secrets vault (Infisical)

One self-hosted Infisical on the Mac (compose profile `vault`, `127.0.0.1:8080`), **one project and one read-only
machine identity per tenant** (project slug = tenant id). A tenant opts in by having `~/.finance-vault/<id>.json`
(`poetry run python -m finance.vault_admin tenant <id>`) while `FINANCE_VAULT_URL` is set; every other tenant keeps
its `.env`. The sync worker fetches the secrets into the scraper's environment only (`FINANCE_VAULT_LOADED=1`);
the API has no vault access. Households type their own secrets in the UI; agents never do. Infisical-specific code
is only `finance/vault.py` + `finance/vault_admin.py` (`FINANCE_VAULT_BACKEND` keeps it swappable). Design,
setup and what it does not fix: **docs/secrets-vault.md**; rollout: issue #61.

## Notifications inbox

The "לטיפול" actions (`data/actions.py` + `validation_actions`) are also mirrored into Postgres
`notifications` by `data/cashflow.py` (best-effort, via `db/inbox.py sync`; a dead DB never stops the
digest). Every action carries `category` (PROBLEM | WARNING | REMINDER | SUGGESTION | INFO), `type`
(camelCase event) and `subject` (`{kind, ...}`), and its period-stable `id` is the row key. The digest owns
the content and `resolved_at`; the household owns `read_at` / `snoozed_until_at` / `archived_at` (the only
columns `finance_api` can update); `pushed_at` is stamped only by `finance/push.py`. Visible = not archived, not resolved, not
snoozed; snoozing marks unread. GraphQL: `api/schema/inbox.graphql`; inbox mutations do **not** signal a
ledger rebuild. Live changes arrive as `event: notification` on `/api/sync/events`. Details: `api/README.md`.

### Tenants and the back office

Every row of customer data belongs to one tenant; Postgres RLS enforces it (design, onboarding order and the
checklist for a new tenant-owned table: **docs/tenancy.md**). The household's original data is the master
tenant `default`. **Tenant and user operations (create or suspend a household, add or remove a member,
provision or deprovision their Cognito account, audit access) are the `backoffice` agent's job**, using
`poetry run python sync/backoffice.py …` from the main checkout and the `backoffice-tenants|members|access`
skills; the `tenant-mgmt` skill is for changing the code. The platform admin is hard-coded in
`finance/tenancy.py`; the `/tenants` screen does the same through the Mac's worker, because the API holds no AWS
credentials. Never apply Terraform or a live migration without the user's go-ahead on a shown plan.

