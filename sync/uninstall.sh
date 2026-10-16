#!/usr/bin/env bash
# Stop the worker agent (and clean up the legacy temporal agent) and stop the
# Temporal container. Leaves ~/.temporal/finance.db and logs.
set -uo pipefail
for label in me.yarinsa.finance-worker me.yarinsa.temporal; do
  launchctl bootout "gui/$UID/$label" 2>/dev/null && echo "unloaded $label"
  rm -f "$HOME/Library/LaunchAgents/$label.plist"
done
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docker compose -f "$REPO/docker-compose.yml" stop temporal
