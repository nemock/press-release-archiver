#!/usr/bin/env bash
# install.sh — install the press-release-archiver/analyzer/presenter slash commands
# to ~/.claude/commands/ so they're available in any Claude Code session.
#
# Usage:
#   bash install.sh        # interactive: ask before overwriting
#   bash install.sh --force  # overwrite existing commands without asking

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMANDS_SRC="$SCRIPT_DIR/.claude/commands"
COMMANDS_DST="$HOME/.claude/commands"
FORCE=0

for arg in "$@"; do
  case "$arg" in
    --force|-f) FORCE=1 ;;
    --help|-h)
      cat <<EOF
Install press-release-archiver slash commands.

Copies the 5 commands in $COMMANDS_SRC to $COMMANDS_DST so they're
available globally in any Claude Code session (rather than only when
working inside the cloned repo).

Options:
  --force, -f    Overwrite existing command files without asking
  --help, -h     Show this help

After install, set the PRESS_RELEASE_SKILL_DIR environment variable
to point to this repo (so the commands know where to find the Python
scripts):

  export PRESS_RELEASE_SKILL_DIR="$SCRIPT_DIR"

Add that line to your ~/.zshrc or ~/.bashrc to persist it.
EOF
      exit 0
      ;;
  esac
done

if [ ! -d "$COMMANDS_SRC" ]; then
  echo "ERROR: $COMMANDS_SRC not found. Run this script from inside the cloned repo." >&2
  exit 1
fi

mkdir -p "$COMMANDS_DST"

echo "Installing press-release commands → $COMMANDS_DST"
echo ""

for cmd in "$COMMANDS_SRC"/*.md; do
  name=$(basename "$cmd")
  if [ -f "$COMMANDS_DST/$name" ] && [ "$FORCE" -eq 0 ]; then
    read -r -p "  $name already exists. Overwrite? [y/N] " ans
    if [[ "$ans" =~ ^[Yy]$ ]]; then
      cp "$cmd" "$COMMANDS_DST/"
      echo "    [overwrote] $name"
    else
      echo "    [skipped]   $name"
    fi
  else
    cp "$cmd" "$COMMANDS_DST/"
    echo "  [installed] $name"
  fi
done

echo ""
echo "Done. Commands available in any Claude Code session:"
echo ""
ls "$COMMANDS_DST"/pr-*.md 2>/dev/null | xargs -n1 basename | sed 's/\.md$//' | sed 's/^/  \//'

echo ""
echo "To complete setup, point Claude at the skill scripts by setting:"
echo ""
echo "    export PRESS_RELEASE_SKILL_DIR=\"$SCRIPT_DIR\""
echo ""
echo "Add that line to your ~/.zshrc or ~/.bashrc to persist it."
echo ""
echo "Test with:  /pr-archive \"Stryker\" SYK"
