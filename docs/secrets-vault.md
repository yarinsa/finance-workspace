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
- **Households type their own secrets** in the Infisical UI. Nothing here reads, sets or invents a
  credential value.
- **The API gets no vault access.** Planned self-service path: the app posts a secret to the API, which
  starts a Temporal workflow; the Mac's worker writes it into the tenant's project (the Harel SMS-code
  pattern). The Infisical UI is never exposed to the internet.

## How it flows

`sync.activities.scrape` calls `finance.vault.fetch_tenant_secrets(tenant)` for an opted-in tenant and puts the
result in the scraper child's environment with `FINANCE_VAULT_LOADED=1`; `scrapers/tenant.mjs` `loadEnv`
then reads no file for another tenant. Secrets never reach the digest or deploy steps and are never written
to disk by the app. An outage (connection refused, timeout, HTTP 5xx) is a retryable failure; no identity,
access denied or a bad configuration is final. Messages never carry a secret.

## Setup (the user does these, on the Mac)

1. In `.env`: `INFISICAL_DB_PASSWORD`, `INFISICAL_ENCRYPTION_KEY` (`openssl rand -hex 16`),
   `INFISICAL_AUTH_SECRET` (`openssl rand -base64 32`). **Back the encryption key and auth secret up off the
   Mac**: without them the vault cannot be decrypted.
2. `docker compose --profile vault up -d --wait`
3. `poetry run python -m finance.vault_admin bootstrap you@example.com` (once; asks for the admin password).
4. Per tenant: `poetry run python -m finance.vault_admin tenant <tenant-id>`, then enter that tenant's
   secrets in the UI at http://localhost:8080 (project = the tenant id, environment `prod`).
5. Set `FINANCE_VAULT_URL=http://127.0.0.1:8080` in the worker's environment and
   `launchctl kickstart -k gui/$(id -u)/me.yarinsa.finance-worker`. Then run one sync for that tenant.

## What the vault does not fix

- **At rest on the Mac nothing improves:** a 0600 identity file replaces a 0600 env file, and the vault's own
  root keys sit in `.env`. What it adds is a UI, an audit log, per-tenant projects and isolation.
- **The platform admin can read every household's secrets** (Infisical instance admin, and the Mac owner).
  This is an accepted exception to "the platform admin gets no access to another tenant's data" in
  `docs/tenancy.md`, unavoidable while the Mac runs every scrape.
- **Pin the image:** `infisical/infisical:latest-postgres` is unpinned; pin a release tag.
- The `vaultdata` volume has no backup yet.

## Not done

- Migrating the master tenant's `.env` (bank logins first; Postgres, API origin secret and VAPID are needed at
  container start, so last).
- Python outside the sync worker (CLI runs of `db/*`, `sync/`) still reads `.env`.
- The self-service flow above; the vault root keys in the Keychain; backups; rotation reminders; one vault
  fetch per source instead of per dump script.
