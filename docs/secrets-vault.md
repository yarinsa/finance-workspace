# Secrets vault (Infisical)

Status: **built and tested end to end** against a real Infisical: bootstrap, tenant projects, scoped identities,
a fetch through `sync.activities._scrape_env`, the Node loader, cross-tenant refusal, outage, and (2026-10-31)
the API's self-service write (create, update, status, delete) from the app container.
Nothing is moved out of `.env` yet. A tenant's **scrapes** use the vault only when the worker has
`FINANCE_VAULT_URL` AND the tenant has a read-identity file, so scraping stays as it was until you opt in.

## Current state (2026-10-31)

- The vault runs on this Mac (`docker compose --profile vault`, `127.0.0.1:8080`) and was bootstrapped once:
  admin `yarinsasson2@gmail.com`; its generated password is in `~/.finance-vault/admin-password` (0600, move it to a
  password manager and delete the file), the instance-admin token in `~/.finance-vault/admin.json`.
- Both tenants have a project, a read identity (`~/.finance-vault/<id>.json`) and a write identity
  (`~/.finance-vault-write/<id>.json`): `default` (`00000000-0000-4000-8000-000000000001`) and `tairsasson`
  (`d7adcdd1-57a9-4e86-9d73-6a8e7b308ed9`). `tairsasson`'s project is empty; `default`'s holds the 15 source logins
  copied from `.env` on 2026-10-31 with `vault_admin import-env` (the `.env` copies are still there).
- The API container has `FINANCE_VAULT_URL=http://vault:8080` (from `FINANCE_API_VAULT_URL` in `.env`) and the
  write identities mounted, so the syncs screen can set secrets now.
- **The sync worker does NOT have `FINANCE_VAULT_URL`**, so nothing a household enters in the app is used by a
  scrape yet. Before setting it (setup step 5) fill every tenant's project: an opted-in non-master tenant reads
  its secrets from the vault only, never from `~/.finance-tenants/<id>.env`.
- **Not end-to-end encrypted.** Secrets are encrypted at rest with `INFISICAL_ENCRYPTION_KEY`, but the vault, the
  API (write identity, see #63) and the Mac's worker all handle them in the clear. It buys isolation, a UI and an
  audit log, not secrecy from the platform admin.

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

1. `infra/vault-keys.sh` generates `INFISICAL_DB_PASSWORD`, `INFISICAL_ENCRYPTION_KEY` and `INFISICAL_AUTH_SECRET`
   into `.env` plus `FINANCE_API_VAULT_URL`; it never overwrites one that is set (a new encryption key would make
   every stored secret undecryptable). **Back the encryption key and auth secret up off the Mac**: without them
   the vault cannot be decrypted.
2. `docker compose --profile vault up -d --wait`
3. `poetry run python -m finance.vault_admin bootstrap you@example.com` (once; asks for the admin password,
   which is only needed to sign in to the Infisical UI; the script keeps a token, not the password).
4. Per tenant: `poetry run python -m finance.vault_admin tenant <tenant-id>` (project + read identity + write
   identity), then enter that tenant's secrets in the syncs screen or in the UI at http://localhost:8080
   (project = the tenant id, environment `prod`). A tenant set up before self-service:
   `poetry run python -m finance.vault_admin upgrade <tenant-id>`.
5. Set `FINANCE_VAULT_URL=http://127.0.0.1:8080` in the worker's environment and
   `launchctl kickstart -k gui/$(id -u)/me.yarinsa.finance-worker`. Then run one sync for that tenant.
6. For the app: `FINANCE_API_VAULT_URL=http://vault:8080` in `.env` (step 1 adds it), then
   `docker compose --profile api up -d --build api` (the image carries the sources' manifests). On Docker Desktop
   the 0600 write identities were readable by the container's user without further changes.

## Operating it

- **Import a household's logins from an env file:** `FINANCE_VAULT_URL=http://127.0.0.1:8080 poetry run python -m
  finance.vault_admin import-env <tenant-id> [path/.env]`. Copies only the manifests' connection variables that have
  a value (never Postgres, the API origin secret, VAPID or AWS), prints names only, and is safe to re-run (it
  replaces). It does not remove anything from the file.
- **Add a household:** create the tenant (backoffice-tenants skill), then
  `poetry run python -m finance.vault_admin tenant <tenant-id>`; the app can set its secrets right away.
- **A tenant that has a project but no write identity:** `vault_admin upgrade <tenant-id>`.
- **Restart after a change:** `docker compose --profile vault up -d` (vault), `docker compose --profile api up -d
  --build api` (API); the worker with `launchctl kickstart -k gui/$(id -u)/me.yarinsa.finance-worker`.
- **The app says "vault: …" when saving:** the message is the vault's HTTP status only (never a body, never a
  value). 403 = the write identity lacks the role; 404 on login = identity file stale; "unreachable" = the vault
  container is down or the API has no `FINANCE_VAULT_URL`.
- **Infisical API facts learned the hard way:** list/read take `workspaceSlug`; create/update/delete take
  `projectSlug` (a `workspaceSlug` body gets "You must provide projectSlug or workspaceId"). Code:
  `finance/vault.py` (`set_secret`, `secret_status`), tests in `sync/tests/test_vault.py` (fake HTTP), and the
  GraphQL layer in `api/gql/sync.py` + `api/tests/test_sync_secrets.py`.
- **Lost the admin password:** reset it in Infisical or re-bootstrap on a fresh `vaultdata` volume; the encryption
  key is what protects stored secrets, not the password.

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
- Self-service **reveal** (deliberately not built: set/missing only); the vault root keys in the Keychain; backups;
  rotation reminders; one vault fetch per source instead of per dump script.
- The API's write identity can also read its tenant's secrets (issue #63).
