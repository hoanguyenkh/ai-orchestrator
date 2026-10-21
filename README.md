# ai-orchestrator

Route each task to the model that fits it. Claude Code is the first provider. Codex, Cursor, and Grok are not set up yet.

## Claude Code

The main session runs on `opus` with `effortLevel` `high`. Those defaults live in [`providers/claude/config.json`](providers/claude/config.json). `init.sh` writes `"model"`, `"effortLevel"`, and `"CLAUDE_CODE_SUBAGENT_MODEL": "haiku"` in `~/.claude/settings.json`. Implementation, review, and other main-session work stay there so the prompt cache is shared. Planning still uses the `tier-opus` subagent. Haiku fetches logs and does PR or image-tag work. The main session analyzes the fetched lines and decides whether to continue. Each subagent sets `disallowedTools: Agent` so it cannot spawn nested subagents, while inheriting all other tools including MCP.

| Stage | Where it runs | Model |
| --- | --- | --- |
| Built-in codebase search (`Explore`) | `Explore` override (`effort: low`, `omitClaudeMd: true`, read-only) | `haiku` |
| Fetch logs of a service or an agent | `tier-haiku` subagent (`effort: medium`, `omitClaudeMd: true`, `maxTurns: 15`) | `haiku` |
| Analyze those logs and decide the next step | **Main session directly** | `opus` (`effortLevel: high`) |
| Make/merge a PR or bump an image tag | `tier-haiku` subagent (`effort: medium`, `omitClaudeMd: true`, `maxTurns: 15`) | `haiku` |
| Plan code or plan a feature | `tier-opus` subagent (`effort: high`) | `opus` |
| Implement, improve, review, re-review, and everything else | **Main session directly** (shared context & prompt cache) | `opus` (`effortLevel: high`) |

`haiku`, `sonnet`, and `opus` are aliases for the latest model in that family. A new Opus release does not require an edit to the agent files.

When a prompt only asks for main-session work (fix, implement, improve, review, re-review), the `UserPromptSubmit` hook stays silent and the main Opus session handles it immediately. When a prompt needs Haiku, a plan, or multiple stages, the hook injects a routing hint so the main session delegates those stages and keeps the code/review stages on itself.

Install or update (backs up existing files under `~/.claude/orchestrator-backups/<timestamp>/`):

```bash
providers/claude/init.sh          # main, code, and review on opus, effort high
providers/claude/init.sh sonnet   # same routing, main session on sonnet
```

`--explain` checks the classifier only:

```bash
python3 providers/claude/route.py --explain "review log service payment xem có lỗi không"
```

To see which agent a real session starts, run the smoke test:

```bash
python3 providers/claude/smoke.py
```
