---
name: backoffice-access
description: Back-office knowledge of how access really works - Cognito accounts, the invitation email, per-tenant groups, the edge gate and enforce_tenant_data - plus the audit that compares the database with Cognito and the checklist for "she cannot sign in" or "I get 403". Activate when someone cannot sign in, sees 403 on /data, lost access, did not get the invitation, or when the user asks who has access to what.
---

# Back office: access

## The model

- **Postgres is the source of truth** (users, memberships, tenant status). Cognito follows it; nothing in Cognito is
  decided by hand. The API never touches AWS: the app asks the Mac's worker (`sync_tenant_access`) and this CLI calls
  the same code.
- **Account**: Cognito username = email. The pool is admin-create-only (no self sign-up). Creating a user makes
  Cognito email the invitation (template in `infra/main.tf`, `invite_message_template`; temporary password valid
  one day; default sender, so a few dozen emails a day at most). After a day, re-invite: `tenant-groups.sh` cannot
  resend, so disable/re-add is not enough; use `aws cognito-idp admin-create-user --message-action RESEND` (ask first).
- **Group** `tenant-<tenant-id>`: put in the id token as `cognito:groups`. The edge Lambda serves
  `/data/t/<tenant-id>/*.json` only to that group, and (with `enforce_tenant_data = true`, on since 2026-10-30)
  `/data/*.json` only to `tenant-00000000-0000-4000-8000-000000000001`. The Lambda has no database, so a group change
  reaches a session at its **next token**: sign out and in, or wait up to an hour.
- **API**: needs a membership (header `X-Tenant-Id`, or the user's only tenant); 403 `forbidden` / `no_tenant` /
  `tenant_suspended` otherwise. This is checked live, with no token delay.

## Audit

`poetry run python sync/backoffice.py audit` (read-only) prints one line per difference: `MISSING` (member without an
account), `GROUP` (group does not match membership/suspension), `ENABLED` (no active tenant but account enabled),
`ORPHAN` (enabled account with no membership). Repair one person with `... access SLUG EMAIL`.

## "She cannot sign in"

1. Does the account exist and is it enabled? `audit` says `MISSING`/`ENABLED`; or
   `aws cognito-idp admin-get-user --user-pool-id <pool> --username EMAIL` (status `FORCE_CHANGE_PASSWORD` = has not
   used the invitation yet; the temporary password expires after 1 day).
2. Did the invitation arrive? Spam folder; address typo (compare with `list`); Cognito default sender limits.
3. Disabled because she lost her last tenant? `... member add SLUG EMAIL` re-enables.

## "403 on data" / "empty app"

1. Signed in before the group was added → sign out and in.
2. `audit`: group missing → `access SLUG EMAIL`.
3. Tenant suspended → `list` shows status; `tenant activate`.
4. Several tenants and none chosen → the app's switcher / `X-Tenant-Id` (API returns 400 `tenant_required`).
5. Data not published yet for a new tenant: its first scheduled sync has not run (`backoffice-tenants`, step 4).

## Safety

Read-only checks are always fine. Changing Cognito settings, Terraform, or `enforce_tenant_data` needs the user's
go-ahead on a shown plan. Never delete users. Never put the platform admin in another tenant's data group.
