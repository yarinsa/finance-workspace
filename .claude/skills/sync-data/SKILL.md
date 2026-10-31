---
name: sync-data
description: Rebuild digested data and push only the JSON to the S3 bucket behind my-finance.yarinsa.me, then invalidate /data/*. Use to publish fresh numbers; for code changes use `deploy-app`.
---

# Sync data to the bucket

Pushes the current digested JSON to `s3://<bucket>/data/` (bucket from
`terraform output bucket` in `infra/`). The app bundle is untouched — use the
`deploy-app` skill for that. No bank login is involved: it works from whatever
raw dumps are already on disk.

## Steps

1. **Rebuild the digested outputs** from the repo root (read-only over scraped
   data, safe to re-run). Order matters — `validate`, `forecast`, `cashflow` and `goals`
   read what `digest` writes, and `cashflow` turns validation failures into actions:

   ```bash
   poetry run python data/digest.py && poetry run python data/validate.py && poetry run python data/forecast.py && poetry run python data/cashflow.py && poetry run python data/goals.py
   ```

   Stop and report if any step fails — don't upload a half-rebuilt set.
   If the user wants *fresh bank data*, run `refresh-all` first (it needs them
   to log in); otherwise say plainly that the sync reflects the last scrape and
   roughly when that was (`ls -lt data/*/raw`).

2. **Upload:**

   ```bash
   ./infra/deploy.sh --data-only
   ```

   Uploads each JSON with `no-cache` and invalidates `/data/*`.
   It does **not** touch `data/sync-status.json`: that file is owned by the
   Temporal worker (`sync/`), which overwrites it on every workflow step.

3. **Report:** the site URL, bucket, invalidation id, and any
   `skip <file>.json` warnings (a missing file means that dashboard page will
   refuse to render).

## Guardrails

- The data goes straight from gitignored `data/digested/` to the bucket — never
  commit it, copy it anywhere public, or make the bucket/objects public.
- Never run `terraform apply` here. If outputs are missing, report it.
- If `aws` isn't authenticated, tell the user to sign in — don't hunt for keys.
