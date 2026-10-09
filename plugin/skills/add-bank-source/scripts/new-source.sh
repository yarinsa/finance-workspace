#!/usr/bin/env bash
#
# Scaffold a new bank/service scraper skill from the templates in this skill.
#
# Usage:
#   new-source.sh <name> <port> [login_url]
#     name       short kebab id, e.g. "hapoalim"  (skill becomes <name>-refresh)
#     port       CDP debug port, next free one (see registry in ../SKILL.md)
#     login_url  optional; placed in the generated SKILL.md launch block
#
# Creates:
#   .claude/skills/<name>-refresh/SKILL.md
#   .claude/skills/<name>-refresh/scripts/dump.sh   (chmod +x, with TODO markers)
set -euo pipefail

NAME="${1:?usage: new-source.sh <name> <port> [login_url]}"
PORT="${2:?usage: new-source.sh <name> <port> [login_url]}"
LOGIN_URL="${3:-https://CHANGEME.example.com}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"          # .../add-bank-source/scripts
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
TPL_DIR="$SCRIPT_DIR/templates"

SKILL_DIR="$REPO_ROOT/.claude/skills/${NAME}-refresh"
if [ -e "$SKILL_DIR" ]; then
  echo "Refusing to overwrite existing $SKILL_DIR" >&2
  exit 1
fi
mkdir -p "$SKILL_DIR/scripts"

# Fill placeholders: __NAME__, __PORT__, __LOGIN_URL__
sed -e "s|__NAME__|$NAME|g" -e "s|__PORT__|$PORT|g" -e "s|__LOGIN_URL__|$LOGIN_URL|g" \
  "$TPL_DIR/SKILL.md.tpl" > "$SKILL_DIR/SKILL.md"
sed -e "s|__NAME__|$NAME|g" -e "s|__PORT__|$PORT|g" -e "s|__LOGIN_URL__|$LOGIN_URL|g" \
  "$TPL_DIR/dump.sh.tpl" > "$SKILL_DIR/scripts/dump.sh"
chmod +x "$SKILL_DIR/scripts/dump.sh"

echo "Created $SKILL_DIR"
echo "  SKILL.md"
echo "  scripts/dump.sh   (fill in the TODO endpoint list after discovery)"
echo ""
echo "Next:"
echo "  1. Launch Chrome on port $PORT (see the generated SKILL.md)."
echo "  2. Have the USER log in."
echo "  3. Discover endpoints, then replace the TODO list in dump.sh."
echo "  4. Add the port/profile row to add-bank-source/SKILL.md's registry."
