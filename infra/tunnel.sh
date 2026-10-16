#!/usr/bin/env bash
# Expose the local ledger API (127.0.0.1:8787) to CloudFront through Tailscale Funnel.
#
#   tunnel.sh        publish /api via Funnel and print the next steps
#   tunnel.sh --off  stop publishing /api (kill switch / rollback)
#
# This script never installs or logs in to Tailscale — you do that. Funnel also
# has to be allowed in your tailnet policy file (admin console -> Access
# controls) with a nodeAttrs entry granting the "funnel" attribute to this
# machine; again, that is yours to do. The public URL is harmless without the
# X-Origin-Secret header that only CloudFront sends.
set -euo pipefail

PORT=${FINANCE_API_PORT:-8787}
TARGET="http://127.0.0.1:${PORT}/api"   # the mount prefix is stripped, so keep /api in the target

TS=$(command -v tailscale || true)
if [ -z "$TS" ] && [ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]; then
  TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale
fi
if [ -z "$TS" ]; then
  cat >&2 <<'MSG'
tailscale is not installed. Install it and sign in yourself, then re-run:

  brew install --cask tailscale
  open -a Tailscale     # log in to your tailnet

MSG
  exit 1
fi

case "${1:-}" in
  "") ;;
  --off)
    # `off` needs the same flags as the command that turned the path on.
    "$TS" funnel --https=443 --set-path=/api off
    echo "Funnel /api is off. The dashboard falls back to read-only."
    echo "To remove all Funnel/Serve config on this node: tailscale funnel reset"
    exit 0
    ;;
  *) echo "usage: $0 [--off]" >&2; exit 2 ;;
esac

if ! "$TS" status >/dev/null 2>&1; then
  echo "Tailscale is installed but not connected. Log in yourself (open -a Tailscale), then re-run." >&2
  exit 1
fi

HOST=$("$TS" status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')

"$TS" funnel --bg --https=443 --set-path=/api "$TARGET"

cat <<EOF

Funnel is publishing https://${HOST}/api -> ${TARGET}

Next steps (in order):
  1. Set the origin in infra/terraform.tfvars:
       api_origin_domain = "${HOST}"
  2. cd infra && terraform apply
  3. Copy the origin secret into .env (do not paste it anywhere else):
       FINANCE_API_ORIGIN_SECRET=\$(terraform output -raw api_origin_secret)
  4. docker compose up -d api

If the funnel command reported that Funnel is not enabled, add the "funnel"
attribute for this machine under nodeAttrs in your tailnet policy file
(https://login.tailscale.com/admin/acls) and re-run this script.

Status:   $TS funnel status
Turn off: $0 --off
EOF
