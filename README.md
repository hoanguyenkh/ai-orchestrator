# ai-orchestrator

Route each task to the model that fits it. Claude Code is the first provider. Codex, Cursor, and Grok are not set up yet.

## Claude Code

The main session runs on `opus` with `effortLevel` `high`. Those defaults live in [`providers/claude/config.json`](providers/claude/config.json). `init.sh` writes `"model"`, `"effortLevel"`, and `"CLAUDE_CODE_SUBAGENT_MODEL": "opus"` in `~/.claude/settings.json`. That default is Opus so a subagent that pins no `model` of its own does not quietly land on Haiku; every agent below pins its own `model`, so the table is the complete list of work that leaves the main model. Implementation, review, and the judgement calls stay on that session so the prompt cache is shared. Planning still uses the `tier-plan` subagent. `tier-haiku` fetches logs and returns the lines only; it cannot write files. `tier-haiku-release` commits the named paths, pushes, and opens the pull request as one stage, and bumps an image tag; the main session writes the commit message and the pull request title and body. A commit-only request stops after the commit: it does not push and does not open a pull request. It merges only when the prompt asks to merge. `Explore` is limited to `Glob`, `Grep`, and `Read`. Each subagent sets `disallowedTools` so it cannot spawn nested subagents.

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
| PR and an image-tag bump together | One `tier-haiku-release` call, when the bump follows the PR and no merge was asked for. A requested merge keeps them in two calls, because the image is built from the merged commit | `haiku` |
| Plan code or plan a feature | `tier-plan` subagent (`effort: high`) | `fable` |
| Everything else | **Main session directly** | `opus` (`effortLevel: high`) |

`haiku`, `sonnet`, and `opus` are aliases for the latest model in that family. A new Opus release does not require an edit to the agent files.

When a prompt only asks for main-session work (fix, implement, improve, review, re-review), the `UserPromptSubmit` hook stays silent and the main Opus session handles it immediately. When a prompt needs Haiku, a plan, or multiple stages, the hook injects a routing hint so the main session delegates those stages and keeps the code and the review on itself.

Three things do not depend on the prompt wording:

- **Release work never waits for a hint.** The hook reads only the user's prompt, so it cannot see the commit the main session decides to make partway through a turn: "sửa luôn" produces no hint, and the commit, the push and the pull request would then stay on Opus. The skill therefore sends every commit, push, pull request and image-tag move to `tier-haiku-release` whatever the hook said. The main session still writes the message, the title and the body, and passes the exact paths and the diff summary it already has.
- **A prompt that never says `log` can still be a log fetch.** "check xem lỗi trên robinhood" and "review 8 agent trong 6 cycle" used to fall through to the main session silently, which is how raw log lines end up in the Opus context and stay there. Those now get an ambiguity hint (`log-maybe`) naming `tier-haiku`; the main session decides, because only it can tell a running-service question from a question about the code. A source-level word (`code`, `pr`, `diff`, `file`, `test`, `refactor`, ...) rules the prompt out, so a code review is never mistaken for a log fetch.
- **The hint says what a spawn actually saves.** The hook reads `transcript_path` from its own payload and takes the tokens of the last usage record, which is what every further main-session request re-reads. Above `_CONTEXT_FLOOR` (150k) the hint says the spawn is worth it; below it the hint says delegating saves little context, except for a release stage, which goes to `tier-haiku-release` for its staging rules regardless. Reading the tail of a 5.5 MB transcript costs about 1 ms, and the whole hook stays at roughly 26 ms.

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
