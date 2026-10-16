#!/usr/bin/env bash
# Install the local Temporal dev server + finance worker as launchd agents and
# register the daily amex-sync schedule. Safe to re-run.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs/finance-sync"
LABELS=(me.yarinsa.temporal me.yarinsa.finance-worker)

command -v /opt/homebrew/bin/temporal >/dev/null || { echo "temporal CLI missing: brew install temporal" >&2; exit 1; }
mkdir -p "$AGENTS" "$LOGS" "$HOME/.temporal"

# Python env for the worker (data/ stays stdlib-only; only sync/ needs this).
[ -x "$REPO/.venv/bin/python" ] || python3 -m venv "$REPO/.venv"
"$REPO/.venv/bin/pip" install -q -r "$REPO/sync/requirements.txt"

for label in "${LABELS[@]}"; do
  dest="$AGENTS/$label.plist"
  sed -e "s|__REPO__|$REPO|g" -e "s|__HOME__|$HOME|g" "$REPO/sync/launchd/$label.plist" > "$dest"
  launchctl bootout "gui/$UID/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID" "$dest"
  launchctl kickstart "gui/$UID/$label"  # RunAtLoad does not always fire on bootstrap
  echo "loaded $label"
done

echo -n "waiting for Temporal on 7233"
for _ in $(seq 1 60); do
  if nc -z 127.0.0.1 7233 2>/dev/null; then echo " ok"; break; fi
  echo -n "."; sleep 1
done
nc -z 127.0.0.1 7233 || { echo " timed out; see $LOGS" >&2; exit 1; }

"$REPO/.venv/bin/python" "$REPO/sync/schedule.py"
echo "UI: http://localhost:8233   logs: $LOGS"
