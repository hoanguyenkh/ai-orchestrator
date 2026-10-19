#!/usr/bin/env bash
# Install or update the Claude Code subagents, skill, and prompt hook.
# Safe to re-run: agent files and the hook entry are replaced in place.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
HOOK="$CLAUDE/hooks/orchestrator-route.py"

mkdir -p "$CLAUDE/agents" "$CLAUDE/skills/model-router" "$CLAUDE/hooks"

cp "$ROOT/agents/"tier-*.md "$CLAUDE/agents/"
cp "$ROOT/skill/SKILL.md" "$CLAUDE/skills/model-router/SKILL.md"
cp "$ROOT/route.py" "$HOOK"
chmod +x "$HOOK"

python3 "$ROOT/route.py" --install-hook "$CLAUDE/settings.json" "$HOOK"

echo "Updated Claude Code config in $CLAUDE"
echo "  agents: tier-haiku, tier-sonnet, tier-opus"
echo "  skill:  skills/model-router"
echo "  hook:   UserPromptSubmit -> $HOOK"
echo
echo "If this is the first time ~/.claude/agents exists, restart Claude Code once."
echo "Then ask normally, or force a worker with @tier-haiku, @tier-sonnet, or @tier-opus."
