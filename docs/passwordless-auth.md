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

## Rollout (user steps)

1. Review `terraform plan`, then `terraform apply`.
2. Request SES production access.
3. Test end to end on a throwaway address.
4. Owner: register a passkey and sign in with an email code, then rotate the owner password to a
   discarded random value (`admin-set-user-password --permanent`) — last.

## Open checks

- Confirm EMAIL_OTP requires SES DEVELOPER email and a CONFIRMED user.
- Confirm PASSWORD can't be dropped from `allowed_first_auth_factors`.
- Confirm managed login honours `login_hint`; can the password option be hidden by branding?
