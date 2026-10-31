---
name: backoffice-tenants
description: Create, suspend or reactivate a tenant (household) and onboard a second household end to end. Use when asked to add, open, freeze or reactivate a household/customer.
---

# Back office: tenants

Facts: `docs/tenancy.md`. Run everything from the main checkout (`/Users/yarinsa/Code/Finance`).
The master tenant is `default` (`00000000-0000-4000-8000-000000000001`): never suspended.

## Look first

```
poetry run python sync/backoffice.py list      # slug, name, status, members
poetry run python sync/backoffice.py audit     # database vs Cognito; "in sync" or the differences
```

## Create a tenant

`poetry run python sync/backoffice.py tenant create SLUG "NAME" owner@example.com`

- slug: lower-case letters, digits, dashes. The owner is required; the platform admin is **not** made a member
  (they would otherwise belong to two tenants and every API call would need `X-Tenant-Id`).
- This writes the tenant (with its horizon buckets) and the owner's membership, then provisions the owner:
  Cognito creates the account if new and **emails the invitation** (temporary password, valid one day) and puts
  them in group `tenant-<id>`. Tell the user before running it for an address with no account.
- The same is available in the app: `/tenants` → "משק בית חדש".

## Suspend / reactivate

`... tenant suspend SLUG` / `... tenant activate SLUG`. The API answers 403 for a suspended tenant, and every
member is taken out of its Cognito group (their account is disabled only if they have no other active tenant).
Reactivating restores the groups. Suspension never deletes data.

## Onboard a second household (full sequence)

1. Preconditions (check, do not change): `infra/terraform.tfvars` has `enforce_tenant_data = true`; `audit` is clean.
2. `tenant create` as above. Confirm the invitation went to the right address.
3. **Credentials**: the household types its own bank logins into `~/.finance-tenants/<tenant-id>.env`, mode 600,
   on the Mac, **or**, once the vault is set up (`docs/secrets-vault.md`), `poetry run python -m finance.vault_admin tenant <tenant-id>`
   and the household types its secrets in the Infisical UI (project = the tenant id, env `prod`); a tenant with
   `~/.finance-vault/<tenant-id>.json` uses the vault, any other keeps its env file. Only self-login sources run for a tenant: discount (business, mortgage, checking), leumi, cal, amex,
   max. You never see or write the secrets; you can check the file (or the identity file) exists and has mode 600.
4. **Schedule**: `poetry run python sync/schedule.py --tenant <tenant-id>` (06:50 and 22:30), then `--trigger` for a
   first run. Follow it in the Temporal UI (localhost:8233): workflow `finance-sync-run-<tenant-id>`.
5. The owner opens the app, signs in with the emailed temporary password, chooses a new one (14+ characters), and
   sees their own data under `/data/t/<tenant-id>/` after the first digest publishes.
6. `audit` again and report.

## Known limits

Live sync status (`/syncs`) is the master tenant's. Chrome-driven sources (harel, more, analyst, riseup) are
master-only. A tenant is never deleted.
