---
name: model-router
description: >
  Route stages before delegating. Use when the user mentions routing, which
  model, Haiku, Sonnet, Opus, check log, MCP, lên plan, git commit, make PR,
  or bump image tag.
---

# Model router

The main session runs on {{Main}} (`"model": "{{main_model}}"`, `"effortLevel": "{{main_effort}}"`).

Follow the orchestrator hint when this conversation has one. That hint lists the stages in order. This skill does not restate that procedure.

When no hint is present, do the work on the main {{Main}} session. That covers implementation, review, and re-review.

- `tier-opus` writes a plan
- `tier-haiku` fetches the logs through MCP and returns the lines only
- `tier-haiku-release` commits the reviewed paths and bumps an image tag. The main session writes the commit message
- the main {{Main}} session opens the pull request and does not create the git commit

Codebase search may use `Explore`. An explicit @-mention (`@tier-haiku`, `@tier-haiku-release`, `@tier-opus`) overrides the hint.
