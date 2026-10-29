#!/usr/bin/env bash
# Keep Cognito groups in step with tenant memberships (docs/tenancy.md).
#
#   tenant-groups.sh add    TENANT_ID EMAIL     put EMAIL in group tenant-<TENANT_ID> (creates it)
#   tenant-groups.sh remove TENANT_ID EMAIL
#   tenant-groups.sh sync                       make every membership in Postgres a group member
#
# The edge-auth Lambda has no database: it serves /data/t/<tenant>/ only to a session whose id
# token lists "tenant-<tenant>" in cognito:groups. A change shows up in a session when its
# token is next issued (at most an hour; signing out and in is immediate). This needs AWS
# credentials, so it runs on the Mac and nothing internet-facing can run it.
set -euo pipefail
cd "$(dirname "$0")"
POOL=${USER_POOL_ID:-$(terraform output -raw user_pool_id)}
UUID_RE='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'

ensure_group() {
  aws cognito-idp get-group --user-pool-id "$POOL" --group-name "$1" >/dev/null 2>&1 ||
    aws cognito-idp create-group --user-pool-id "$POOL" --group-name "$1" \
      --description "Members of tenant ${1#tenant-}" >/dev/null
}

change() { # add|remove tenant email
  [[ $2 =~ $UUID_RE ]] || { echo "error: bad tenant id" >&2; exit 2; }
  local group="tenant-$2"
  if [[ $1 == add ]]; then
    ensure_group "$group"
    aws cognito-idp admin-add-user-to-group --user-pool-id "$POOL" --group-name "$group" --username "$3"
  else
    aws cognito-idp admin-remove-user-from-group --user-pool-id "$POOL" --group-name "$group" --username "$3"
  fi
  echo "$1 $3 -> $group"
}

case "${1:-}" in
  add|remove) [[ $# -eq 3 ]] || { sed -n 2,9p "$0" >&2; exit 2; }; change "$1" "$2" "$3" ;;
  sync)
    cd ..
    poetry run python db/tenants.py memberships | while IFS=$'\t' read -r tenant email; do
      (cd infra && change add "$tenant" "$email") || echo "skipped $email (not a Cognito user?)" >&2
    done ;;
  *) sed -n 2,9p "$0" >&2; exit 2 ;;
esac
