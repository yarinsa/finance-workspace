# Tenancy

Every piece of customer data belongs to exactly one **tenant**. A **user** (global, keyed by
the verified Cognito email) acts in a tenant only through a **membership** (`owner | admin |
member`). Isolation is enforced by Postgres, not by per-query filters.

## How the tenant is resolved (API)

1. `current_user` verifies the session and the email allow-list, then `api/tenancy.py` loads the
   user's memberships.
2. The tenant is the `X-Tenant-Id` header; with no header, the user's only tenant. Several
   tenants and no header → `400 tenant_required`. A tenant they are not a member of (or that
   does not exist) → `403`; no membership at all → `403 no_tenant`; suspended → `403`.
3. The result lives in `request.state.tenant`. `api.app.db()` binds it on the pooled connection
   (`app.tenant_id`), clears it on the way out, and **raises** when a request has none. Nothing
   downstream reads a tenant from client input; a `tenant_id` in a body or GraphQL input is never
   used or exposed (`Binding` hides it).
4. CloudFront must forward `X-Tenant-Id` to the origin (origin request policy) when a
   switcher exists. Until then every user has one tenant and needs no header.

## Enforcement

- **Database.** Each tenant-owned table has `tenant_id uuid NOT NULL REFERENCES tenants`, a column
  default `current_setting('app.tenant_id')::uuid`, `ENABLE` + `FORCE ROW LEVEL SECURITY` and one
  policy `USING/WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)`. An unbound
  setting makes the cast fail: no tenant means an error, never all rows. Views are
  `security_invoker`. Roles `finance_api` (API) and `finance_app` (host jobs) have no
  `BYPASSRLS` and own nothing. Migrations and `db/tenants.py` use the privileged owner role.
- **Host jobs** (`digest`, `cashflow`, `db/*.py`, sync): `ledger.connect(tenant_id=…)` takes
  `finance_app` and pins the tenant. It resolves the tenant from the argument, the bound
  `TenantContext`, or `FINANCE_TENANT_ID`, and otherwise raises. Only `__main__` entry points call
  `use_cli_tenant()`, which defaults to the default tenant (the single-household behaviour).
- **Natural keys** (`(txn_date, abs_amount)`, `plan_targets.key`, …) include `tenant_id`; uniques
  (`name`, `slug`, `merchant`, …) are per tenant. `ON CONFLICT` targets must list `tenant_id`.

## Platform admin (the master tenant)

`finance.tenancy.PLATFORM_ADMIN_EMAILS` (hard-coded: `yarinsasson2@gmail.com`) may manage the tenant
registry through GraphQL: `tenants`, `tenantCreate(input: {slug, name, ownerEmail})`,
`tenantMemberSet(id, input: {email, role})`, `tenantMemberRemove`, `tenantSetStatus`. Every field errors
for anyone else; the check is on the verified session email. The `default` tenant is the master: it
cannot be suspended, and no tenant can lose its last owner. Being a platform admin gives **no access to
another tenant's data**: reading it still needs a membership (the admin is deliberately not made a member
of tenants they create, so their own app keeps working without `X-Tenant-Id`). Migration 0019 gives
`finance_api` the few writes this needs (tenants, users, memberships, a new tenant's horizons).

## Admin (CLI)

`poetry run python db/tenants.py create SLUG NAME`, `member add EMAIL [TENANT] [--role …]`,
`suspend|activate`, `list`. The migration makes everyone in `FINANCE_API_ALLOWED_EMAILS` an owner of
the `default` tenant (`00000000-0000-4000-8000-000000000001`) holding all pre-existing data.

## Adding a tenant-owned table

1. Model in `finance/tables.py` with `tenant_id: … = Field(sa_column=_tenant())` (primary key part if
   the table is keyed by a natural key; uniques include `tenant_id`).
2. Alembic: add the column (nullable → backfill → NOT NULL + FK + default), index leading with
   `tenant_id`, `ENABLE`/`FORCE ROW LEVEL SECURITY`, `CREATE POLICY tenant_isolation` as in 0017.
3. Add the table to `OWNED` in `db/tests/test_tenancy.py` (a test fails for any unclassified table).
4. Grants for `finance_api` if the API touches it (`finance_app` gets default privileges).
5. Views over it: `WITH (security_invoker = true)` and join on `tenant_id`.
6. A cross-tenant test: A cannot list, read, update or delete B's rows.

## Per-tenant files, publishing and sync

- **Files.** `finance/paths.py`: the master tenant keeps `data/<source>/…` and `data/digested/`; any other
  tenant lives in `data/tenants/<id>/` with the same tree. The tenant is chosen per process by
  `FINANCE_TENANT_ID` (the sync activities set it on every child process).
- **Published data.** `infra/deploy.sh --data-only --tenant ID` uploads to `data/t/<id>/`. The edge-auth
  Lambda serves `/data/t/<id>/<file>.json` only to a session whose Cognito groups include `tenant-<id>`
  (it has no database, so the group mirrors the membership: `infra/tenant-groups.sh add|remove|sync`).
  With `enforce_tenant_data = true` the master tenant's `/data/*.json` needs `tenant-0000…0001` too.
- **Scrapers.** `scrapers/tenant.mjs`: another tenant reads only `~/.finance-tenants/<id>.env` (0600) and
  writes to its own tree; it never loads the repo `.env`, so a missing credential stops the run instead of
  logging in as another household. Only self-login sources (`discount*`, `leumi`, `cal`, `amex`, `max`) can run for
  another tenant; Chrome-driven ones (harel, more, analyst, riseup) stay master-only.
- **Sync.** `FinanceSyncWorkflow` takes `opts.tenant_id`; every activity receives it. Schedules:
  `python3 sync/schedule.py --tenant ID` (`finance-sync-<ID>`, 06:50 and 22:30). Rebuild after an edit is one
  `LedgerRebuildWorkflow` per tenant (`ledger-rebuild-<ID>`; the master keeps `ledger-rebuild`).
  `sync_status` and its live screen stay the master tenant's; other tenants are followed in the Temporal UI.
- **Push.** `finance/push.py` scopes its connection to the bound tenant: subscriptions and inbox of one tenant.
- **App.** `GET /api/me` lists the user's tenants without needing one chosen. With several, the sidebar
  switcher stores the choice, sends `X-Tenant-Id` (and `?tenant=` on the live stream), reads
  `/data/t/<id>/…` and reloads, so nothing of the previous tenant stays in memory.

## Onboarding a second tenant (in this order)

1. `terraform apply` with the Lambda change (`enforce_tenant_data` still false), then `infra/tenant-groups.sh sync`
   so every current member is in their tenant group; sign out and in once. Then set `enforce_tenant_data = true`
   and apply. **Do this before step 2**: until then any signed-in user can read the master tenant's files.
2. As platform admin: `tenantCreate(slug, name, ownerEmail)`; `infra/tenant-groups.sh add <tenant-id> <owner-email>`.
3. The owner's bank logins go in `~/.finance-tenants/<tenant-id>.env` (mode 600) on the Mac, typed by that household.
4. `poetry run python sync/schedule.py --tenant <tenant-id>`, then `--trigger`.
5. The owner signs in again (the group is in the id token) and sees their own data.

## Not done

Live sync status per tenant (`sync_status` is global), log tagging, a tenant-switcher design review, composite
foreign keys, invites. Chrome-driven sources for a second tenant.
