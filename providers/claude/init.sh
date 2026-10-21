#!/usr/bin/env bash
# Install or update the Claude Code subagents, skill, and prompt hook.
# Copies are backed up before any file is replaced.
#
# The main session model comes from config.json (default: opus, effort high).
# Pass sonnet to install that model instead:
#   init.sh
#   init.sh sonnet
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
HOOK="$CLAUDE/hooks/orchestrator-route.py"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$CLAUDE/orchestrator-backups/$STAMP"
MAIN_OVERRIDE="${1:-}"

if [ "$#" -gt 1 ]; then
  echo "usage: $0 [opus|sonnet]" >&2
  exit 1
fi
if [ -n "$MAIN_OVERRIDE" ] && [ "$MAIN_OVERRIDE" != "opus" ] && [ "$MAIN_OVERRIDE" != "sonnet" ]; then
  echo "usage: $0 [opus|sonnet]" >&2
  exit 1
fi

backup_file() {
  local src="$1"
  local rel="$2"
  if [ -f "$src" ]; then
    mkdir -p "$BACKUP/$(dirname "$rel")"
    cp "$src" "$BACKUP/$rel"
  fi
}

render() {
  local src="$1"
  local dest="$2"
  mkdir -p "$(dirname "$dest")"
  if [ -n "$MAIN_OVERRIDE" ]; then
    python3 "$ROOT/route.py" --render "$src" "$dest" --main-model "$MAIN_OVERRIDE"
  else
    python3 "$ROOT/route.py" --render "$src" "$dest"
  fi
}

mkdir -p "$CLAUDE/agents" "$CLAUDE/skills/model-router" "$CLAUDE/hooks"

for src in "$ROOT/agents/"*.md; do
  name="$(basename "$src")"
  backup_file "$CLAUDE/agents/$name" "agents/$name"
  render "$src" "$CLAUDE/agents/$name"
done
rm -f "$CLAUDE/agents/tier-sonnet.md"
backup_file "$CLAUDE/skills/model-router/SKILL.md" "skills/model-router/SKILL.md"
backup_file "$HOOK" "hooks/orchestrator-route.py"
backup_file "$CLAUDE/settings.json" "settings.json"

render "$ROOT/skill/SKILL.md" "$CLAUDE/skills/model-router/SKILL.md"
cp "$ROOT/route.py" "$HOOK"
chmod +x "$HOOK"

if [ -n "$MAIN_OVERRIDE" ]; then
  read -r MODEL EFFORT SUB < <(python3 "$ROOT/route.py" --print-config --main-model "$MAIN_OVERRIDE")
  python3 "$ROOT/route.py" --install-hook "$CLAUDE/settings.json" "$HOOK" --main-model "$MAIN_OVERRIDE"
else
  read -r MODEL EFFORT SUB < <(python3 "$ROOT/route.py" --print-config)
  python3 "$ROOT/route.py" --install-hook "$CLAUDE/settings.json" "$HOOK"
fi

echo "Updated Claude Code config in $CLAUDE"
echo "  agents: tier-haiku, tier-opus, Explore (main/code/review stay on the main session; MCP is inherited)"
echo "  skill:  skills/model-router"
echo "  hook:   UserPromptSubmit -> $HOOK"
echo "  model:  main session set to $MODEL, effort $EFFORT, default subagent model set to $SUB"
if [ -d "$BACKUP" ]; then
  echo "  backup: $BACKUP"
else
  echo "  backup: nothing to replace"
fi
echo
echo "The hook only adds a hint. It does not switch the model or start a subagent."
echo "Keep the main session on $MODEL. Restart Claude Code if ~/.claude/agents is new."
echo "Install Sonnet instead with: $0 sonnet"
echo "Classifier check: python3 $ROOT/route.py --explain \"review log service payment xem có lỗi không\""
echo "Real session check: python3 $ROOT/smoke.py"
