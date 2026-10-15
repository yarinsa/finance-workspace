---
name: sync-data
description: Rebuild the digested finance data and push ONLY the JSON (cashflow, snapshot, transactions, goals, forecast) to the private S3 bucket behind https://my-finance.yarinsa.me, then invalidate /data/*. No app build. Activate when the user asks to sync/push/upload data to the bucket(s), update the dashboard's numbers, or publish fresh data. For shipping code changes to the dashboard itself, use `deploy-app`.
---

# Sync data to the bucket

Pushes the current digested JSON to `s3://<bucket>/data/` (bucket from
`terraform output bucket` in `infra/`). The app bundle is untouched — use the
`deploy-app` skill for that. No bank login is involved: it works from whatever
raw dumps are already on disk.

## Steps

1. **Rebuild the digested outputs** from the repo root (read-only over scraped
   data, safe to re-run). Order matters — `forecast`, `cashflow` and `goals`
   read what `digest` writes:

   ```bash
   python3 data/digest.py && python3 data/forecast.py && python3 data/cashflow.py && python3 data/goals.py
   ```

   Stop and report if any step fails — don't upload a half-rebuilt set.
   If the user wants *fresh bank data*, run `refresh-all` first (it needs them
   to log in); otherwise say plainly that the sync reflects the last scrape and
   roughly when that was (`ls -lt data/*/raw`).

2. **Upload:**

   ```bash
   ./infra/deploy.sh --data
   ```

   Uploads each JSON with `no-cache` and invalidates `/data/*`.

3. **Report:** the site URL, bucket, invalidation id, and any
   `skip <file>.json` warnings (a missing file means that dashboard page will
   refuse to render).

## Guardrails

- The data goes straight from gitignored `data/digested/` to the bucket — never
  commit it, copy it anywhere public, or make the bucket/objects public.
- Never run `terraform apply` here. If outputs are missing, report it.
- If `aws` isn't authenticated, tell the user to sign in — don't hunt for keys.
