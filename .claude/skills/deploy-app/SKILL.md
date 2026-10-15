---
name: deploy-app
description: Build the Plangram dashboard (app/) and push ONLY the app bundle to the private S3 bucket behind https://my-finance.yarinsa.me, then invalidate CloudFront. Does not touch the data. Activate when the user asks to deploy/ship/release the app, dashboard code or UI changes. For pushing fresh numbers, use `sync-data`.
---

# Deploy the app

Builds `app/` and uploads the bundle to the private bucket (from
`terraform output bucket` in `infra/`). The digested JSON under `/data/` is
left as-is — use the `sync-data` skill to update it. If the user wants both,
run `./infra/deploy.sh` with no flag (after rebuilding data as `sync-data`
describes).

## Steps

1. **Sanity-check the build** before shipping — `deploy.sh` runs it too, but a
   failure here is cheaper to read:

   ```bash
   cd app && pnpm build
   ```

2. **Deploy:**

   ```bash
   ./infra/deploy.sh --app-only
   ```

   Runs `pnpm install --frozen-lockfile && pnpm build`, syncs hashed assets with
   immutable caching (`--delete`, excluding `data/*`), uploads `index.html` with
   `no-cache`, and invalidates `/*`. Use a long timeout (~10 min) and filter the
   noisy `upload:`/`Completed` lines when summarizing.

3. **Report:** the site URL, the new asset hashes, and the invalidation id.
   Mention if there are uncommitted changes in `app/` — the deployed build then
   doesn't match any commit.

## Guardrails

- Prod fetches data at runtime from the auth-gated `/data/` path — never bundle
  digested JSON into the build or relax that fetch.
- Never run `terraform apply` here. If outputs are missing, report it.
- If `aws` isn't authenticated, tell the user to sign in — don't hunt for keys.
