#!/usr/bin/env bash
# Keep Cognito in step with tenant memberships (docs/tenancy.md).
#
#   tenant-groups.sh add    TENANT_ID EMAIL     put EMAIL in group tenant-<TENANT_ID> (creates the group)
#   tenant-groups.sh remove TENANT_ID EMAIL     take EMAIL out of it (a missing user or group is fine)
#   tenant-groups.sh ensure-user EMAIL          create the account if missing (Cognito emails the
#                                               invitation with a temporary password), re-enable it if disabled
#   tenant-groups.sh disable-user EMAIL         disable the account (reversible; a missing user is fine)
#   tenant-groups.sh sync                       add every membership in Postgres to its group
#
# Normally the app's /tenants screen does this through the Mac's sync worker
# (sync/activities.py `sync_tenant_access`, which decides from the database); this script is that
# worker's hands and a manual fallback. The edge-auth Lambda has no database: it serves
# /data/t/<tenant>/ only to a session whose id token lists "tenant-<tenant>" in cognito:groups,
# which shows up at the next sign-in. Needs AWS credentials, so it runs on the Mac only.
set -euo pipefail
cd "$(dirname "$0")"
POOL=${USER_POOL_ID:-$(terraform output -raw user_pool_id)}
UUID_RE='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
EMAIL_RE='^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'

check_email() { [[ $1 =~ $EMAIL_RE ]] || { echo "error: bad email" >&2; exit 2; }; }

ensure_group() {
  aws cognito-idp get-group --user-pool-id "$POOL" --group-name "$1" >/dev/null 2>&1 ||
    aws cognito-idp create-group --user-pool-id "$POOL" --group-name "$1" \
      --description "Members of tenant ${1#tenant-}" >/dev/null
}

# True if the error text names a missing user or group (nothing to undo).
absent() { grep -qE "UserNotFoundException|ResourceNotFoundException" <<<"$1"; }

change() { # add|remove tenant email
  [[ $2 =~ $UUID_RE ]] || { echo "error: bad tenant id" >&2; exit 2; }
  check_email "$3"
  local group="tenant-$2" out
  if [[ $1 == add ]]; then
    ensure_group "$group"
    aws cognito-idp admin-add-user-to-group --user-pool-id "$POOL" --group-name "$group" --username "$3"
  else
    if ! out=$(aws cognito-idp admin-remove-user-from-group --user-pool-id "$POOL" --group-name "$group" --username "$3" 2>&1); then
      absent "$out" || { echo "$out" >&2; exit 1; }
    fi
  fi
  echo "$1 $3 -> $group"
}

ensure_user() {
  check_email "$1"
  local out
  if out=$(aws cognito-idp admin-get-user --user-pool-id "$POOL" --username "$1" --query Enabled --output text 2>&1); then
    if [[ $out == False ]]; then
      aws cognito-idp admin-enable-user --user-pool-id "$POOL" --username "$1"
      echo "enabled $1"
    else
      echo "exists $1"
    fi
  elif grep -q UserNotFoundException <<<"$out"; then
    # Cognito sends the invitation (the pool's invite template) to this address.
    aws cognito-idp admin-create-user --user-pool-id "$POOL" --username "$1" \
      --user-attributes "Name=email,Value=$1" "Name=email_verified,Value=true" \
      --desired-delivery-mediums EMAIL >/dev/null
    echo "invited $1"
  else
    echo "$out" >&2; exit 1
  fi
}

disable_user() {
  check_email "$1"
  local out
  if out=$(aws cognito-idp admin-disable-user --user-pool-id "$POOL" --username "$1" 2>&1); then
    echo "disabled $1"
  elif grep -q UserNotFoundException <<<"$out"; then
    echo "absent $1"
  else
    echo "$out" >&2; exit 1
  fi
}

case "${1:-}" in
  add|remove) [[ $# -eq 3 ]] || { sed -n 2,13p "$0" >&2; exit 2; }; change "$1" "$2" "$3" ;;
  ensure-user) [[ $# -eq 2 ]] || { sed -n 2,13p "$0" >&2; exit 2; }; ensure_user "$2" ;;
  disable-user) [[ $# -eq 2 ]] || { sed -n 2,13p "$0" >&2; exit 2; }; disable_user "$2" ;;
  sync)
    cd ..
    poetry run python db/tenants.py memberships | while IFS=$'\t' read -r tenant email; do
      (cd infra && change add "$tenant" "$email") || echo "skipped $email (not a Cognito user?)" >&2
    done ;;
  *) sed -n 2,13p "$0" >&2; exit 2 ;;
esac
