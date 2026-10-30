# Secrets vault (Infisical)

Status: **first slice**. The vault service, the client and the sync-worker hook exist; nothing is
moved yet and everything is off until `FINANCE_VAULT_URL` is set. The Infisical REST paths in
`finance/vault.py` (`/api/v1/auth/universal-auth/login`, `/api/v3/secrets/raw?workspaceSlug=…`) were
written from memory of its API and **not yet run against a live instance**: check them first.

## Decisions

- **Infisical, self-hosted, Mac only** (compose profile `vault`, `127.0.0.1:8080`). Same availability as the
  sync worker; Mac off means no scraping anyway. No AWS Secrets Manager for now (cost); the loader is one
  function, so it can be swapped later.
- **One project per tenant**, slug `tenant-<tenant-id>`, environment `prod`, path `/`.
- **One machine identity (Universal Auth) per tenant**, scoped to that project only. Its client id/secret
  go in `~/.finance-vault/<tenant-id>.json` (`{"client_id","client_secret"}`, mode 0600). A tenant with no
  identity file fails; it never borrows another's or falls back to the repo `.env`.
- **Households type their own secrets** in the Infisical UI (a member of their project). No agent types,
  reads or invents credentials, same rule as every bank login here.
- **The API gets no vault access.** Self-service entry through the app (a `/tenants` link into the
  Infisical UI, or a write-only endpoint) is a later step; the API container holds no read identity.

## How it flows

`sync.activities.scrape` calls `finance.vault.fetch_tenant_secrets(tenant)` when the vault is on and puts
the result in the scraper child's environment with `FINANCE_VAULT_LOADED=1`; `scrapers/tenant.mjs`
`loadEnv` then reads no file. Secrets never reach the digest or deploy steps and are never written to disk.
A vault failure is a non-retryable `ScrapeFailed` whose message carries no secret.

## Setup (the user does these)

1. Add `INFISICAL_DB_PASSWORD`, `INFISICAL_ENCRYPTION_KEY`, `INFISICAL_AUTH_SECRET` to `.env`
   (see `.env.example`). **Back up the encryption key and auth secret off the Mac.**
2. `docker compose --profile vault up -d --wait`, open http://localhost:8080, create the admin account.
3. Per tenant: create project `tenant-<id>`, a machine identity limited to it, write its identity file.
4. Enter the tenant's secrets in the UI, then set `FINANCE_VAULT_URL=http://127.0.0.1:8080` for the worker
   and kickstart it (`launchctl kickstart -k gui/$(id -u)/me.yarinsa.finance-worker`).

## Not done

- Migrating the master tenant's `.env` (bank logins first; Postgres, API origin secret and VAPID are
  needed at container start, so last).
- The Python side outside the sync worker (CLI runs of `db/*`, `sync/` still read `.env`).
- Self-service entry from the app, rotation reminders, pinning the Infisical image tag.
