---
name: backoffice-members
description: Back-office procedures for people - add or invite a member to a household, remove or offboard one, change a role, and what provisioning and deprovisioning do to their Cognito account. Activate when the user asks to add, invite, give access to, remove, offboard or revoke someone, or to make someone an owner/admin/member of a tenant.
---

# Back office: members

Run from the main checkout. Roles: `owner` (manage the tenant), `admin`, `member`. A tenant always keeps one owner.

## Add or invite

`poetry run python sync/backoffice.py member add SLUG person@example.com [--role owner|admin|member]` (default `member`)

What happens, in order, and it is the same as `/tenants` → "הוספה":
1. Postgres: the user (created by email) and the membership. Emails are stored lower-case.
2. Cognito, decided from the database: a **new** person gets an account and Cognito **emails the invitation**; a
   disabled one is re-enabled; then they join group `tenant-<tenant-id>`.
3. Output line, e.g. `person@example.com: invited,added`.

Before running: confirm the address with the user if it was typed from memory, and say that a new person will
receive an invitation email. Promoting someone to owner or admin needs the user to say so explicitly.
After: they sign in (or sign out and in again if they already had an account) so their token carries the group.

## Remove or offboard

`... member remove SLUG person@example.com`

- They lose the tenant's group at once (their next sign-in has no access to its files; the API refuses at the next
  request because the membership is gone).
- If this was their **last active tenant**, the account is **disabled** (`removed,disabled`). Nothing is deleted;
  adding them again re-enables it. The platform admin is never disabled.
- The last owner of a tenant cannot be removed or demoted (the registry refuses).

## Change a role

`... member add SLUG person@example.com --role admin` (adding again updates the role).

## If it failed

The database change stands and the output says `PROVISIONING FAILED: …`. Common causes: no AWS credentials in this
shell, the pool name not resolvable (`terraform output` from `infra/`), a typo in the address. Fix, then
`poetry run python sync/backoffice.py access SLUG person@example.com` (idempotent). See `backoffice-access`.
