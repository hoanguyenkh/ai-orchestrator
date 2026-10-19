# ai-orchestrator

Route each task to the model that fits it. Claude Code is the first provider. Codex, Cursor, and Grok are not set up yet.

## Claude Code

The main session runs on `sonnet` (`init.sh` sets `"model": "sonnet"` and `"CLAUDE_CODE_SUBAGENT_MODEL": "haiku"` in `~/.claude/settings.json`). To keep latency and token usage low, **Sonnet tasks run directly on the main session** with zero subagent spawn overhead, while **Opus** and **Haiku** stages are delegated to [subagents](https://code.claude.com/docs/en/sub-agents) in `~/.claude/agents/`. Each subagent sets `disallowedTools: Agent` so it cannot spawn nested subagents, while inheriting all other tools including MCP.

| Stage | Where it runs | Model |
| --- | --- | --- |
| Built-in codebase search (`Explore`) | `Explore` override (`effort: low`, `omitClaudeMd: true`, read-only) | `haiku` |
| Check logs of a service or an agent | `tier-haiku` subagent (`effort: medium`, `omitClaudeMd: true`, `maxTurns: 15`) | `haiku` |
| Make/merge a PR or bump an image tag | `tier-haiku` subagent (`effort: medium`, `omitClaudeMd: true`, `maxTurns: 15`) | `haiku` |
| Plan code or plan a feature | `tier-opus` subagent (`effort: high`) | `opus` |
| Implement, improve, review, re-review, and everything else | **Main session directly** (shared context & prompt cache) | `sonnet` |

`haiku`, `sonnet`, and `opus` are aliases for the latest model in that family. A new Sonnet release does not require an edit to the agent files.

When a prompt only asks for Sonnet work (fix, implement, improve, review, re-review), the `UserPromptSubmit` hook stays silent and the main Sonnet session handles it immediately. When a prompt needs Haiku, Opus, or multiple stages, the hook injects a routing hint so the main session delegates the Haiku/Opus stages and keeps the code/review stages on itself.

Install or update (backs up existing files under `~/.claude/orchestrator-backups/<timestamp>/`):

```bash
providers/claude/init.sh
```

`--explain` checks the classifier only:

```bash
python3 providers/claude/route.py --explain "review log service payment xem có lỗi không"
```

To see which agent a real session starts, run the smoke test:

```bash
python3 providers/claude/smoke.py
```
