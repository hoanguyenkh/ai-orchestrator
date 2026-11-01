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

- `tier-plan` writes a plan
- `tier-haiku` fetches the logs and returns the lines only. Analyze them on the main {{Main}} session
- `tier-haiku-release` commits the named paths, pushes, and opens the pull request as one stage, and bumps an image tag. The main {{Main}} session writes the commit message and the pull request title and body
- a commit with no pull request asked for is a `commit only` delegation: `tier-haiku-release` stops after the commit
- merge only when the prompt asks to merge

Codebase search may use `Explore`. An explicit @-mention (`@tier-haiku`, `@tier-haiku-release`, `@tier-plan`) overrides the hint.
