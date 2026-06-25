#!/bin/bash
set -euo pipefail

# Nur in Claude Code on the Web ausfuehren
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

SKILLS_REPO="https://github.com/guertlergoertz/Skills.git"
TEMP_DIR=$(mktemp -d)
trap "rm -rf \"$TEMP_DIR\"" EXIT

echo "Syncing global skills from guertlergoertz/Skills..."
git clone --depth 1 --quiet "$SKILLS_REPO" "$TEMP_DIR/skills"

# Skills nach ~/.claude/skills/ synchronisieren
mkdir -p ~/.claude/skills
cp -rf "$TEMP_DIR/skills/claude-config/.claude/skills/." ~/.claude/skills/

# Globale CLAUDE.md nach ~/.claude/CLAUDE.md kopieren
# (enthaelt Caveman-Mode, Design-Regeln etc.)
if [ -f "$TEMP_DIR/skills/claude-config/CLAUDE.md" ]; then
  cp "$TEMP_DIR/skills/claude-config/CLAUDE.md" ~/.claude/CLAUDE.md
fi

echo "Skills synced successfully:"
ls ~/.claude/skills/
