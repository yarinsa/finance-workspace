---
name: tenant-mgmt
description: Manage tenants (households) — create one, add or remove members, suspend it, onboard a second household end to end (database, Cognito group, credentials file, sync schedule), or change code that touches tenant-owned data (a new table, an RLS policy, a scraper path). Activate when the user asks about tenants, memberships, a second household/customer, platform admin, tenant isolation, X-Tenant-Id, the /tenants screen, or `enforce_tenant_data`.
---

# Tenant management

Design and rules: `docs/tenancy.md` (read it before changing anything). Every row of customer data
belongs to one tenant; Postgres Row-Level Security enforces it; files, publishing and sync are per tenant.
The household's original data is the **master tenant** `00000000-0000-4000-8000-000000000001`
(slug `default`); it keeps the old `data/` and `/data/*.json` paths.

## Who may do what

- **Platform admin** = `finance.tenancy.PLATFORM_ADMIN_EMAILS` (hard-coded: yarinsasson2@gmail.com). Only they
  can manage the registry (GraphQL `tenants`, `tenantCreate`, `tenantMemberSet`, `tenantMemberRemove`,
  `tenantSetStatus`; the `/tenants` screen). It gives **no access to another tenant's data**: reading it
  needs a membership.
- The master tenant cannot be suspended; a tenant keeps at least one owner.
- CLI (owner DB role, on the Mac): `poetry run python db/tenants.py list|create|member add|member remove|suspend|activate|memberships`.

## Onboarding a second household — in this order

1. **Edge enforcement must already be on** (`enforce_tenant_data = true` in the gitignored `infra/terraform.tfvars`;
   it is, since 2026-10-30). If not: apply the Lambda change, `infra/tenant-groups.sh sync`, sign out/in, then set it.
2. **Create it**: `/tenants` screen (or `tenantCreate(slug, name, ownerEmail)`). The admin is *not* made a member
   (otherwise they would belong to two tenants and every API call would need `X-Tenant-Id`).
3. **Cognito account and group**: automatic. The `/tenants` screen (and `sync/backoffice.py`, see the `backoffice-*`
   skills and the `backoffice` agent) asks the Mac's worker (`TenantAccessWorkflow` → `sync_tenant_access`), which reads
   Postgres and runs `infra/tenant-groups.sh`: a member of an active tenant gets an account (invited by email if new)
   and the group; anyone else is removed; an account with no access left is disabled. The API holds no AWS credentials.
   **Operating tenants and people is the back-office agent's job**; this skill is for changing the code.
4. **Credentials**: the household types its own bank logins into `~/.finance-tenants/<tenant-id>.env`, mode 600,
   on the Mac. **Never type, read or invent credentials**; same rule as every bank login in this repo. Only
   self-login sources run for another tenant (`discount*`, `leumi`, `cal`, `amex`, `max`).
5. **Schedule**: `poetry run python sync/schedule.py --tenant <tenant-id>` (06:50 and 22:30), then `--trigger`.
6. They sign in again and see their own data (`/data/t/<tenant-id>/…`).

## Rules that keep it safe

- **Never plan and apply Terraform in one step**, and never apply without the user's go-ahead on the shown plan.
  AWS changes (`terraform apply`, Cognito groups) are the user's call; do them only when told to.
- A **live migration** needs the order: merge to master, stop the `api` container, `poetry run python db/ledger.py migrate`
  in the main checkout, rebuild `api`, `launchctl kickstart -k gui/$(id -u)/me.yarinsa.finance-worker`, check `/api/health`.
  Never point worktree code with a new migration at the live DB (see worktree notes); test against a throwaway DB
  (`FINANCE_TEST_DB=finance_test_<name>`). Do not terminate Postgres backends on the live server.
- Check that `FINANCE_API_ALLOWED_EMAILS` people have memberships after a migration (`db/tenants.py list`); the
  migration reads that variable from the process environment, not from `.env`.
- Host-side data access goes through `ledger.connect(tenant_id=…)` (role `finance_app`, RLS). Only `__main__`
  entry points default to the master tenant (`use_cli_tenant()`); the data layer never does.

## Changing code that touches tenant data

Checklist for a new tenant-owned table (also in `docs/tenancy.md`): `tenant_id` in `finance/tables.py`
(`_tenant()`), Alembic migration (column, backfill, NOT NULL, FK, default, RLS `ENABLE`+`FORCE`, policy
`tenant_isolation`), key/unique constraints include `tenant_id`, `ON CONFLICT` targets list it, add the table to
`OWNED` in `db/tests/test_tenancy.py` (a test fails for any unclassified table), `security_invoker` on views,
a cross-tenant test (A cannot list, read, update or delete B's rows). Tests: `poetry run pytest` with
`DATABASE_URL` set and `FINANCE_TEST_DB` pointing at a throwaway DB; `node --test infra/edge-auth/edge-auth.test.js scrapers/tenant.test.mjs`;
`cd app && pnpm exec vitest run`. Four `data/tests/test_forecast_freeze.py` tests fail on a clean checkout; they are not ours.
