# ai-orchestrator

Route each task to the model that fits it. Claude Code is the first provider. Codex, Cursor, and Grok are not set up yet.

## Claude Code

Three [subagents](https://code.claude.com/docs/en/sub-agents) live in `~/.claude/agents/`. Each file pins a model alias and leaves `tools` unset, so the subagent inherits the session tool pool, including MCP. A `tools` allowlist would drop MCP.

The main session stays on Sonnet and coordinates. `init.sh` sets `"model": "sonnet"` in `~/.claude/settings.json`.

| Stage | Subagent | Model |
| --- | --- | --- |
| Check logs of a service or an agent | `tier-haiku` | `haiku` |
| Make a PR or bump an image tag | `tier-haiku` | `haiku` |
| Plan code or plan a feature | `tier-opus` | `opus` |
| Implement or improve | a fresh `tier-sonnet` | `sonnet` |
| Review code | a second fresh `tier-sonnet` | `sonnet` |

`haiku`, `sonnet`, and `opus` are aliases for the latest model in that family. A new Sonnet release does not require an edit to the agent file.

A one-stage sentence goes to that subagent. "Review log ... xem có lỗi không" is Haiku. "Không cần lên plan, fix bug này" drops the cancelled plan and stays on Sonnet. "Lên plan rồi implement và make PR" is not one Opus task: the main session reads it and runs plan, then implement, then the PR.

The `UserPromptSubmit` hook only inserts that hint into context. It does not switch the model and it does not start the subagent. Claude Code still has to call the Agent tool. [Hooks](https://code.claude.com/docs/en/hooks) document `additionalContext` as added context.

Install or update. The script backs up anything it is about to replace under `~/.claude/orchestrator-backups/<timestamp>/`.

```bash
providers/claude/init.sh
```

`--explain` checks the classifier only:

```bash
python3 providers/claude/route.py --explain "review log service payment xem có lỗi không"
```

To see which agent a real session starts, run the smoke test. It sends one log-check prompt through `claude -p` and fails if the Agent tool did not call `tier-haiku`:

```bash
python3 providers/claude/smoke.py
```
