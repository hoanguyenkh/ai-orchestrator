# ai-orchestrator

Route each task to the model that fits it. Claude Code is the first provider. Codex, Cursor, and Grok are not set up yet.

## Claude Code

Three [subagents](https://code.claude.com/docs/en/sub-agents) live in `~/.claude/agents/`. Each file pins a model alias. A `UserPromptSubmit` hook reads the prompt and tells the main thread which subagent to delegate to.

| Request | Subagent | Model |
| --- | --- | --- |
| Check logs of a service for bugs | `tier-haiku` | haiku |
| Make a PR or bump an image tag | `tier-haiku` | haiku |
| Plan code | `tier-opus` | opus |
| Fix, review, and everything else | `tier-sonnet` | sonnet |

A plan stays on Opus even when the plan is about a bug. A task that both fixes code and opens a PR stays on Sonnet.

Install or update:

```bash
providers/claude/init.sh
```

The script copies the agents, the `model-router` skill, and the hook into `~/.claude`. Re-run it after editing the files in `providers/claude/`.

In Claude Code, ask in your own words. To force a worker, @-mention it: `@tier-haiku`, `@tier-sonnet`, `@tier-opus`. Check the decision locally with:

```bash
python3 providers/claude/route.py --explain "check log của service api để xem có bugs ko"
```
