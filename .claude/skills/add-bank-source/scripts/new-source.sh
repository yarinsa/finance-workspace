#!/usr/bin/env bash
#
# Scaffold a new source inside the `refresh` skill from the templates in this skill.
#
# Usage:
#   new-source.sh <name> <port> [login_url]
#     name       short kebab id, e.g. "hapoalim"  
#     port       CDP debug port, next free one (see registry in ../SKILL.md)
#     login_url  optional; placed in the generated reference launch block
#
# Creates:
#   .claude/skills/refresh/references/<name>.md
#   .claude/skills/refresh/scripts/<name>/dump.sh   (chmod +x, with TODO markers)
set -euo pipefail

NAME="${1:?usage: new-source.sh <name> <port> [login_url]}"
PORT="${2:?usage: new-source.sh <name> <port> [login_url]}"
LOGIN_URL="${3:-https://CHANGEME.example.com}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"          # .../add-bank-source/scripts
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
TPL_DIR="$SCRIPT_DIR/templates"

SKILL_DIR="$REPO_ROOT/.claude/skills/refresh"
REF="$SKILL_DIR/references/$NAME.md"
DUMP_DIR="$SKILL_DIR/scripts/$NAME"
if [ -e "$REF" ] || [ -e "$DUMP_DIR" ]; then
  echo "Refusing to overwrite existing $NAME in $SKILL_DIR" >&2
  exit 1
fi
mkdir -p "$SKILL_DIR/references" "$DUMP_DIR"

# Fill placeholders: __NAME__, __PORT__, __LOGIN_URL__
sed -e "s|__NAME__|$NAME|g" -e "s|__PORT__|$PORT|g" -e "s|__LOGIN_URL__|$LOGIN_URL|g" \
  "$TPL_DIR/reference.md.tpl" > "$REF"
sed -e "s|__NAME__|$NAME|g" -e "s|__PORT__|$PORT|g" -e "s|__LOGIN_URL__|$LOGIN_URL|g" \
  "$TPL_DIR/dump.sh.tpl" > "$DUMP_DIR/dump.sh"
chmod +x "$DUMP_DIR/dump.sh"

echo "Created in $SKILL_DIR"
echo "  references/$NAME.md"
echo "  scripts/$NAME/dump.sh   (fill in the TODO endpoint list after discovery)"
echo ""
echo "Next:"
echo "  1. Launch Chrome on port $PORT (see the generated reference)."
echo "  2. Have the USER log in."
echo "  3. Discover endpoints, then replace the TODO list in dump.sh."
echo "  4. Add the port/profile row to add-bank-source/SKILL.md's registry and a row in refresh/SKILL.md."
