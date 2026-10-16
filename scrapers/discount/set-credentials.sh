#!/usr/bin/env bash
# Prompt for the Discount login and write it into <repo>/.env (gitignored).
# Values are read from the terminal only; nothing is echoed or logged.
set -euo pipefail

ENV_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/.env"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

read -r  -p "DISCOUNT_ID (ת.ז): " id
read -rs -p "DISCOUNT_PASSWORD: " password; echo
read -r  -p "DISCOUNT_NUM (user code): " num

set_var() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  grep -v "^${key}=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
}

set_var DISCOUNT_ID "$id"
set_var DISCOUNT_PASSWORD "$password"
set_var DISCOUNT_NUM "$num"
echo "Wrote DISCOUNT_ID, DISCOUNT_PASSWORD, DISCOUNT_NUM to $ENV_FILE"
