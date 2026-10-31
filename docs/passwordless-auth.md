# Passwordless sign-in (email code + passkey)

Replaces the temporary-password invite. Nobody in the household ever knows a password.

## Flow

- **Invite:** the admin adds a member on /tenants → worker → `infra/tenant-groups.sh ensure-user`.
  The script creates the Cognito user with `--message-action SUPPRESS`, sets a long random
  `--permanent` password that is discarded (marks the user CONFIRMED, which EMAIL_OTP needs),
  and sends our own Hebrew invite through SES with one button: the managed-login authorize URL
  with `login_hint=<email>`. Re-inviting just re-sends the email; nothing expires.
- **First sign-in:** "send me a code" → 6-digit email code → managed login offers to save a passkey.
- **After that:** passkey (biometric, `user_verification = required`, counts as two factors).
- **Lost device:** email code, then save a new passkey.

## Pool settings (`infra/main.tf`)

- `allowed_first_auth_factors = ["PASSWORD", "EMAIL_OTP", "WEB_AUTHN"]`. PASSWORD stays only
  because Cognito rejects a list without it (verify); nobody holds a known password.
- `email_configuration` → `DEVELOPER`, SES identity for the domain, `noreply@<domain>`.
- `account_recovery_setting` → `admin_only`, closing "forgot password" as a way back to passwords.
- TOTP stays allowed (MFA OPTIONAL) but is no longer prompted.
- The temporary-password invite template is retired (invites are suppressed).

## SES

Domain identity + DKIM/SPF/DMARC in Route53. Cost: ~$0.10 / 1000 emails — negligible.
Production access (leaving the SES sandbox) is a one-time AWS request — **user step**.

## State (2026-11-01)

Applied to the live pool and verified end to end: a reinvite to the owner and a brand-new account
(created through `ensure-user`, then deleted). The invite button opens managed login with the email
prefilled (`login_hint` works), "send me a code" signs in, and the page offers a passkey. The
account never sees a "choose a new password" step. SES production access was already on.

## Operating it

- Invite: `/tenants` (worker) or `infra/tenant-groups.sh ensure-user EMAIL`; resend: `reinvite EMAIL`.
- From a worktree the script has no terraform state: pass `USER_POOL_ID`, `SITE_DOMAIN`,
  `COGNITO_CLIENT_ID` (`terraform output`).
- The state lives only in the main checkout's `infra/` (gitignored). To plan/apply from another
  worktree, copy `terraform.tfvars` + `terraform.tfstate` in, apply, copy the state back, delete the copies.
- A new SES identity stays "Pending" for a few minutes after its DKIM records are created.

## Still open

- The owner's own password is unchanged. Once the passkey works on every device in use, replace it:
  `admin-set-user-password --permanent` with a random value that is discarded.
- PASSWORD stays in `allowed_first_auth_factors` (not tested whether Cognito accepts dropping it);
  the login page still shows the password field.
