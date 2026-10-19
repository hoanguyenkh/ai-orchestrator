#!/usr/bin/env bash
# Install or update the Claude Code subagents, skill, and prompt hook.
# Copies are backed up before any file is replaced.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
HOOK="$CLAUDE/hooks/orchestrator-route.py"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$CLAUDE/orchestrator-backups/$STAMP"

backup_file() {
  local src="$1"
  local rel="$2"
  if [ -f "$src" ]; then
    mkdir -p "$BACKUP/$(dirname "$rel")"
    cp "$src" "$BACKUP/$rel"
  fi
}

mkdir -p "$CLAUDE/agents" "$CLAUDE/skills/model-router" "$CLAUDE/hooks"

for name in tier-haiku.md tier-opus.md Explore.md; do
  backup_file "$CLAUDE/agents/$name" "agents/$name"
done
rm -f "$CLAUDE/agents/tier-sonnet.md"
backup_file "$CLAUDE/skills/model-router/SKILL.md" "skills/model-router/SKILL.md"
backup_file "$HOOK" "hooks/orchestrator-route.py"
backup_file "$CLAUDE/settings.json" "settings.json"

cp "$ROOT/agents/"*.md "$CLAUDE/agents/"
cp "$ROOT/skill/SKILL.md" "$CLAUDE/skills/model-router/SKILL.md"
cp "$ROOT/route.py" "$HOOK"
chmod +x "$HOOK"

python3 "$ROOT/route.py" --install-hook "$CLAUDE/settings.json" "$HOOK"

echo "Updated Claude Code config in $CLAUDE"
echo "  agents: tier-haiku, tier-opus, Explore (Sonnet runs on main session; MCP is inherited)"
echo "  skill:  skills/model-router"
echo "  hook:   UserPromptSubmit -> $HOOK"
echo "  model:  main session set to sonnet, default subagent model set to haiku"
if [ -d "$BACKUP" ]; then
  echo "  backup: $BACKUP"
else
  echo "  backup: nothing to replace"
fi
echo
echo "The hook only adds a hint. It does not switch the model or start a subagent."
echo "Keep the main session on Sonnet. Restart Claude Code if ~/.claude/agents is new."
echo "Classifier check: python3 $ROOT/route.py --explain \"review log service payment xem có lỗi không\""
echo "Real session check: python3 $ROOT/smoke.py"
