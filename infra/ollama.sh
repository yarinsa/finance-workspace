#!/usr/bin/env bash
# Run Ollama (the local model behind the dashboard's chat assistant) as a login LaunchAgent.
#
#   ollama.sh        install and start it (starts on login, restarts if it dies)
#   ollama.sh --off  stop it and remove the agent
#
# It listens on 127.0.0.1 only. The API container reaches it as host.docker.internal:11434
# (docs/local-assistant.md); never bind it to 0.0.0.0, it has no authentication.
# This script never downloads a model: `ollama pull <model>` is yours to run.
set -euo pipefail

LABEL=me.finance.ollama
BIN=${OLLAMA_BIN:-$HOME/.local/ollama/ollama}
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/finance-ollama.log"
DOMAIN="gui/$(id -u)"

case "${1:-}" in
  "") ;;
  --off)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Ollama agent removed. The assistant answers 'unavailable' until it runs again."
    exit 0
    ;;
  *) echo "usage: $0 [--off]" >&2; exit 2 ;;
esac

[ -x "$BIN" ] || { echo "no Ollama binary at $BIN (set OLLAMA_BIN)" >&2; exit 1; }
if curl -fs -m 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1 && ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "Something else already serves 127.0.0.1:11434 (a manual 'ollama serve'?). Stop it first, then re-run." >&2
  exit 1
fi

mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$BIN</string><string>serve</string></array>
  <key>EnvironmentVariables</key><dict>
    <key>OLLAMA_HOST</key><string>127.0.0.1:11434</string>
    <key>OLLAMA_KEEP_ALIVE</key><string>24h</string>
    <key>OLLAMA_MAX_LOADED_MODELS</key><string>1</string>
    <key>OLLAMA_NUM_PARALLEL</key><string>2</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
PLIST

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Ollama agent started (log: $LOG)."
echo "Next: put FINANCE_API_ASSISTANT_URL=http://host.docker.internal:11434/v1 in .env, then"
echo "  docker compose --profile api up -d api"
