#!/usr/bin/env bash
# Build the dashboard, upload it and the digested JSON to the private bucket,
# then invalidate CloudFront.
#
# The data is uploaded straight from data/digested/ — it is gitignored and never
# passes through version control. It lands in a bucket with all public access
# blocked, reachable only through the auth-gated distribution.
set -euo pipefail

cd "$(dirname "$0")"

BUCKET=$(terraform output -raw bucket)
DIST=$(terraform output -raw distribution_id)
REPO=$(cd .. && pwd)

if [[ -z "$BUCKET" || -z "$DIST" ]]; then
  echo "error: terraform outputs missing — run 'terraform apply' first" >&2
  exit 1
fi

echo "==> building app"
(cd "$REPO/app" && pnpm install --frozen-lockfile && pnpm build)

echo "==> uploading bundle to s3://$BUCKET"
# Hashed assets can cache hard; index.html must not, or a deploy looks like a no-op.
aws s3 sync "$REPO/app/dist/" "s3://$BUCKET/" \
  --delete \
  --exclude "index.html" \
  --exclude "data/*" \
  --cache-control "public,max-age=31536000,immutable"

aws s3 cp "$REPO/app/dist/index.html" "s3://$BUCKET/index.html" \
  --cache-control "no-cache,no-store,must-revalidate" \
  --content-type "text/html; charset=utf-8"

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

echo "==> invalidating CloudFront"
aws cloudfront create-invalidation \
  --distribution-id "$DIST" \
  --paths "/*" \
  --query 'Invalidation.Id' --output text

echo
echo "done: $(terraform output -raw url)"
