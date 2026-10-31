#!/usr/bin/env bash
# Add the vault's root keys to .env, once. Idempotent: a variable that already has a value is NEVER
# touched (a new encryption key would make every stored secret undecryptable). Values are generated
# locally with openssl and are not printed.
#
#   infra/vault-keys.sh [path/to/.env]      # default: .env at the repo root
#
# Afterwards: back INFISICAL_ENCRYPTION_KEY and INFISICAL_AUTH_SECRET up off the Mac (docs/secrets-vault.md).
set -euo pipefail

env_file="${1:-$(cd "$(dirname "$0")/.." && pwd)/.env}"
[ -f "$env_file" ] || { echo "no $env_file" >&2; exit 1; }

has_value() { grep -Eq "^$1=.+" "$env_file"; }
add() {   # add NAME VALUE: only when NAME has no value yet
  if has_value "$1"; then echo "$1: already set, left alone"; return; fi
  sed -i.bak "/^$1=\$/d" "$env_file" && rm -f "$env_file.bak"
  printf '%s=%s\n' "$1" "$2" >> "$env_file"
  echo "$1: added"
}

add INFISICAL_DB_PASSWORD "$(openssl rand -hex 24)"
add INFISICAL_ENCRYPTION_KEY "$(openssl rand -hex 16)"
add INFISICAL_AUTH_SECRET "$(openssl rand -base64 32)"
add FINANCE_API_VAULT_URL "http://vault:8080"
chmod 600 "$env_file"
