#!/usr/bin/env bash
# Publish the dashboard to the private bucket, then invalidate CloudFront.
#
#   deploy.sh              build + upload the app bundle AND the digested data
#   deploy.sh --app-only   bundle only (what CI runs on merge to master)
#   deploy.sh --data-only  digested JSON only (run after a refresh/digest)
#
# The bundle carries no financial data — the app fetches /data/*.json at
# runtime — so CI can ship code without ever seeing the data. The data is
# uploaded straight from data/digested/: it is gitignored and never passes
# through version control or CI. It lands in a bucket with all public access
# blocked, reachable only through the auth-gated distribution.
#
# BUCKET / DISTRIBUTION_ID may come from the environment (CI has no terraform
# state); otherwise they are read from terraform outputs.
set -euo pipefail

MODE=all
case "${1:-}" in
  "") ;;
  --app-only) MODE=app ;;
  --data-only) MODE=data ;;
  *) echo "usage: $0 [--app-only|--data-only]" >&2; exit 2 ;;
esac

cd "$(dirname "$0")"
REPO=$(cd .. && pwd)

BUCKET=${BUCKET:-$(terraform output -raw bucket)}
DIST=${DISTRIBUTION_ID:-$(terraform output -raw distribution_id)}

if [[ -z "$BUCKET" || -z "$DIST" ]]; then
  echo "error: bucket/distribution unknown — run 'terraform apply' or set BUCKET and DISTRIBUTION_ID" >&2
  exit 1
fi

if [[ $MODE != data ]]; then
  echo "==> building app"
  (cd "$REPO/app" && pnpm install --frozen-lockfile && pnpm build)

  echo "==> uploading bundle to s3://$BUCKET"
  # Hashed assets can cache hard; index.html must not, or a deploy looks like a
  # no-op. data/* is excluded so --delete never wipes the published data.
  aws s3 sync "$REPO/app/dist/" "s3://$BUCKET/" \
    --delete \
    --exclude "index.html" \
    --exclude "data/*" \
    --cache-control "public,max-age=31536000,immutable"

  aws s3 cp "$REPO/app/dist/index.html" "s3://$BUCKET/index.html" \
    --cache-control "no-cache,no-store,must-revalidate" \
    --content-type "text/html; charset=utf-8"
fi

if [[ $MODE != app ]]; then
  echo "==> uploading digested data"
  for f in cashflow snapshot transactions goals forecast; do
    src="$REPO/data/digested/$f.json"
    if [[ -f "$src" ]]; then
      aws s3 cp "$src" "s3://$BUCKET/data/$f.json" \
        --cache-control "no-cache,no-store,must-revalidate" \
        --content-type "application/json; charset=utf-8"
    else
      echo "    skip $f.json (not present — run python3 data/digest.py)" >&2
    fi
  done
fi

echo "==> invalidating CloudFront"
aws cloudfront create-invalidation \
  --distribution-id "$DIST" \
  --paths "/*" \
  --query 'Invalidation.Id' --output text

echo
echo "done ($MODE)"
