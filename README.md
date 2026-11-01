# ai-orchestrator

Route each task to the model that fits it. Claude Code is the first provider. Codex, Cursor, and Grok are not set up yet.

## Claude Code

The main session runs on `opus` with `effortLevel` `high`. Those defaults live in [`providers/claude/config.json`](providers/claude/config.json). `init.sh` writes `"model"`, `"effortLevel"`, and `"CLAUDE_CODE_SUBAGENT_MODEL": "opus"` in `~/.claude/settings.json`. That default is Opus so a subagent that pins no `model` of its own does not quietly land on Haiku; every agent below pins its own `model`, so the table is the complete list of work that leaves the main model. Implementation, review, and the judgement calls stay on that session so the prompt cache is shared. Planning still uses the `tier-opus` subagent. `tier-haiku` fetches logs and returns the lines only; it cannot write files. `tier-haiku-release` commits the named paths, pushes, and opens the pull request as one stage, and bumps an image tag; the main session writes the commit message and the pull request title and body. A commit-only request stops after the commit: it does not push and does not open a pull request. It merges only when the prompt asks to merge. `Explore` is limited to `Glob`, `Grep`, and `Read`. Each subagent sets `disallowedTools` so it cannot spawn nested subagents.

| Stage | Where it runs | Model |
| --- | --- | --- |
| Built-in codebase search (`Explore`) | `Explore` override (`tools: Glob, Grep, Read`, `effort: high`, `omitClaudeMd: true`) | `sonnet` |
| Fetch logs of a service or an agent | `tier-haiku` subagent (MCP, Bash, or `Read`/`Grep`; write tools denied, `effort: medium`, `omitClaudeMd: true`, `maxTurns: 15`) | `haiku` |
| Analyze those logs and decide the next step | **Main session directly** | `opus` (`effortLevel: high`) |
| Implement, improve, review, re-review | **Main session directly** (shared context & prompt cache). A loose "review & fix" runs the fix first | `opus` (`effortLevel: high`) |
| Commit, push, and make the PR | `tier-haiku-release` subagent as one stage, after review and the fix are OK. The main session writes the message, title, and body | `haiku` |
| Commit on its own | `tier-haiku-release`, which stops after the commit: no push, no pull request | `haiku` |
| Merge | `tier-haiku-release`, only when the prompt explicitly asks to merge something | `haiku` |
| Bump an image tag | `tier-haiku-release` subagent (`tools: Bash, Glob, Grep, Read, Edit`, `effort: medium`, `maxTurns: 25`) | `haiku` |
| Plan code or plan a feature | `tier-opus` subagent (`effort: high`) | `fable` |
| Everything else | **Main session directly** | `opus` (`effortLevel: high`) |

`haiku`, `sonnet`, and `opus` are aliases for the latest model in that family. A new Opus release does not require an edit to the agent files.

When a prompt only asks for main-session work (fix, implement, improve, review, re-review), the `UserPromptSubmit` hook stays silent and the main Opus session handles it immediately. When a prompt needs Haiku, a plan, or multiple stages, the hook injects a routing hint so the main session delegates those stages and keeps the code and the review on itself.

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
