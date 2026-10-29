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

## Admin

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

## Not done yet

Stages 5 and 6 of the plan: per-tenant data directories, digests, S3 prefixes and the edge-auth
Lambda rewrite, per-tenant scraper credentials and sync fan-out, the Temporal rebuild signal and
`finance/push.py` (they still run for the default tenant only), the frontend tenantId in query
keys, and log tagging. `sync_status` and `category_groups` stay global.
