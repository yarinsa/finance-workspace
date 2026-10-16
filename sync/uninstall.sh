#!/usr/bin/env bash
# Stop and remove the launchd agents. Leaves ~/.temporal/finance.db and logs.
set -uo pipefail
for label in me.yarinsa.finance-worker me.yarinsa.temporal; do
  launchctl bootout "gui/$UID/$label" 2>/dev/null && echo "unloaded $label"
  rm -f "$HOME/Library/LaunchAgents/$label.plist"
done
