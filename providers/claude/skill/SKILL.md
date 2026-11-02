---
name: model-router
description: >
  Route stages before delegating. Use when the user mentions routing, which
  model, Haiku, Sonnet, Opus, check log, lên plan, git commit, make PR, merge,
  or bump image tag.
---

# Model router

The main session runs on {{Main}} (`"model": "{{main_model}}"`, `"effortLevel": "{{main_effort}}"`).

Follow the orchestrator hint when this conversation has one. That hint lists the stages in order. This skill does not restate that procedure.

When no hint is present, do the work on the main {{Main}} session. That covers implementation, review, and re-review.

Release work is the exception, and it does not wait for a hint. The hook only reads the user's prompt, so it never sees the commit you decide to make partway through a turn: a prompt like "sửa luôn" or "đóng gap trước" produces no hint, and the commit, the push and the pull request then stay on {{Main}} by default. Whenever you are about to commit, push, open a pull request, or move an image tag, delegate that stage to `tier-haiku-release`, whether or not this conversation has a hint and whether or not the user used those words. You still write the commit message and the pull request title and body, and you pass the exact paths with them; keep the diff summary you already have in the delegation so the subagent does not spend turns rediscovering it. Two reasons this holds even for one line: the staging rules (`git add -A`, `--force`, `amend` and `reset` are denied there) are the point, and by the time a session reaches its release stage the main context is usually the largest thing in the request.

Log work is the other exception, and it does not wait for a hint either. Whenever you are about to fetch log lines — a Loki or LogQL query, `kubectl logs`, a log file, a provider's log API — delegate that fetch to `tier-haiku`, whether or not this conversation has a hint and whether or not the user said the word "log". Every query the turn needs belongs to that stage, the follow-up ones included: when the first batch of lines raises a new question, send the next query to the same subagent with `SendMessage`, which still holds its context, instead of querying from here, and never re-run a query you have already delegated. You still decide what to ask and you still read the lines; running the query is the part that is priced at Haiku, and the same lines fetched on the main {{Main}} session cost many times more. Iterating on a query shape belongs in the delegation too — name the field and the fallbacks you expect, so the subagent tries them instead of the loop landing on {{Main}}.

- `tier-plan` writes a plan
- `tier-haiku` fetches the logs and returns the lines only. Analyze them on the main {{Main}} session. It runs with `omitClaudeMd`, so it cannot know which backend holds the logs: the delegation carries the access path (the tool or command by name, the datasource, namespace, pod or file it needs, the exact query and limit, and the window). That is the caller's half of this stage, not the subagent's — a log route that "does not work" is usually a prompt that named no backend. Every query in the turn is part of this stage, the follow-ups included
- `tier-haiku-release` commits the named paths, pushes, and opens the pull request as one stage, and bumps an image tag. The main {{Main}} session writes the commit message and the pull request title and body
- a commit with no pull request asked for is a `commit only` delegation: `tier-haiku-release` stops after the commit
- merge only when the prompt asks to merge

Codebase search may use `Explore`. An explicit @-mention (`@tier-haiku`, `@tier-haiku-release`, `@tier-plan`) overrides the hint.
