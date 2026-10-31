# Secrets vault (Infisical)

Status: **built and tested end to end** against a real Infisical (bootstrap, a tenant project, a scoped
identity, a fetch through `sync.activities._scrape_env`, the Node loader, cross-tenant refusal, outage).
Nothing is moved out of `.env` yet. A tenant uses the vault only when it has an identity file, so everything
stays as it was until you opt a household in.

## Decisions

- **Infisical, self-hosted, Mac only** (compose profile `vault`, `127.0.0.1:8080`, its own Postgres and
  Redis, separate from the ledger DB). No cloud secret manager for now (cost). The Infisical-specific code is
  `finance/vault.py` (`fetch_tenant_secrets`) and `finance/vault_admin.py`; everything else sees plain
  `{NAME: value}`. `FINANCE_VAULT_BACKEND` (default `infisical`) names the implementation, so another backend
  can be added next to it and chosen per tenant. No Infisical SDK/CLI, secret references or rotation engine is
  used, to keep that door open (`infisical export` copies a project out).
- **One project per tenant**, slug = the tenant id (Infisical caps a slug at 36 characters, so no prefix),
  environment `prod`, path `/`.
- **One read-only machine identity (Universal Auth) per tenant**, member of that project only. Its client
  id/secret live in `~/.finance-vault/<tenant-id>.json` (0600). Verified: tenant B's identity gets HTTP 403 on
  tenant A's project. A tenant without its own identity file never borrows another's.
- **Per-tenant opt-in.** `FINANCE_VAULT_URL` set AND the tenant's identity file exists means vault; otherwise
  the tenant reads its `.env` / `~/.finance-tenants/<id>.env` as before. Move one household at a time. The
  master tenant still loads the repo `.env` after the vault, which never overrides vault values, so a partly
  migrated household keeps working.
- **Households type their own secrets**, in the syncs screen (פרטי חיבור) or the Infisical UI. Nothing here
  reads, sets or invents a credential value on its own.
- **The API writes secrets, statelessly (built).** The app posts a secret to the API, which writes it
  straight to the tenant's project with a per-tenant write identity (`~/.finance-vault-write/<tenant-id>.json`,
  mounted read-only into the API container; never `~/.finance-vault/`, which holds the admin token). The value
  lives in memory for one request: not in Postgres, not in Temporal (a workflow would persist it in history,
  unlike the short-lived Harel SMS code), not in logs. Only names declared in the source's manifest `x-env` may
  be written, the tenant comes from the auth context, and the app only ever sees set/missing + `updatedAt`
  (no reveal). The Infisical UI is never exposed to the internet.
  **Accepted trade-off:** Infisical's built-in roles have no create-only role, so this identity (`member`) can
  also read its tenant's secrets; the API has no read path, but a compromised API process could read them.
  Tracked as tech debt (create-only custom role or a separate writer service).

## How it flows

`sync.activities.scrape` calls `finance.vault.fetch_tenant_secrets(tenant)` for an opted-in tenant and puts the
result in the scraper child's environment with `FINANCE_VAULT_LOADED=1`; `scrapers/tenant.mjs` `loadEnv`
then reads no file for another tenant. Secrets never reach the digest or deploy steps and are never written
to disk by the app. An outage (connection refused, timeout, HTTP 5xx) is a retryable failure; no identity,
access denied or a bad configuration is final. Messages never carry a secret.

## Setup (the user does these, on the Mac)

1. `infra/vault-keys.sh` generates and adds these to `.env` (never overwrites one that is set). By hand: `INFISICAL_DB_PASSWORD`, `INFISICAL_ENCRYPTION_KEY` (`openssl rand -hex 16`),
   `INFISICAL_AUTH_SECRET` (`openssl rand -base64 32`). **Back the encryption key and auth secret up off the
   Mac**: without them the vault cannot be decrypted.
2. `docker compose --profile vault up -d --wait`
3. `poetry run python -m finance.vault_admin bootstrap you@example.com` (once; asks for the admin password).
4. Per tenant: `poetry run python -m finance.vault_admin tenant <tenant-id>` (project + read identity + write
   identity), then enter that tenant's secrets in the syncs screen or in the UI at http://localhost:8080
   (project = the tenant id, environment `prod`). A tenant set up before self-service:
   `poetry run python -m finance.vault_admin upgrade <tenant-id>`.
5. Set `FINANCE_VAULT_URL=http://127.0.0.1:8080` in the worker's environment and
   `launchctl kickstart -k gui/$(id -u)/me.yarinsa.finance-worker`. Then run one sync for that tenant.
6. For the app: set `FINANCE_API_VAULT_URL=http://vault:8080` in `.env`, make `~/.finance-vault-write/` readable
   by the API container's user (uid 10001; files stay 0600), rebuild and restart the api service
   (`docker compose up -d --build api`; the image now carries the sources' manifests).

## What the vault does not fix

- **At rest on the Mac nothing improves:** a 0600 identity file replaces a 0600 env file, and the vault's own
  root keys sit in `.env`. What it adds is a UI, an audit log, per-tenant projects and isolation.
- **The platform admin can read every household's secrets** (Infisical instance admin, and the Mac owner).
  This is an accepted exception to "the platform admin gets no access to another tenant's data" in
  `docs/tenancy.md`, unavoidable while the Mac runs every scrape.
- **Pin the image:** `infisical/infisical:latest-postgres` is unpinned; pin a release tag.
- The `vaultdata` volume has no backup yet.

## Not done

- Self-service write is untested against a live Infisical: the create/update call uses `workspaceSlug` in the body
  and `viewSecretValue=false` on the list; confirm on the first real run (the tests use a fake).

- Migrating the master tenant's `.env` (bank logins first; Postgres, API origin secret and VAPID are needed at
  container start, so last).
- Python outside the sync worker (CLI runs of `db/*`, `sync/`) still reads `.env`.
- Self-service **reveal** (deliberately not built: set/missing only); the vault root keys in the Keychain; backups; rotation reminders; one vault
  fetch per source instead of per dump script.
