---
name: model-router
description: >
  Split a request into stages: keep Sonnet work on the main session and
  delegate Haiku/Opus stages to their pinned subagents. Use before delegating
  work, and whenever the user mentions routing, which model, Haiku, Sonnet,
  Opus, check log, lên plan, fix, review, make PR, or bump image tag.
---

# Model router

The main session runs on Sonnet (`"model": "sonnet"`). To avoid cold-start latency and duplicate file reads, **do all Sonnet work directly on the main session**. Only call the `Agent` tool when switching to Opus or Haiku.

Route each stage:

- plan code or plan a feature -> `tier-opus` subagent (`model: opus`, `effort: high`)
- check logs of a service or an agent -> `tier-haiku` subagent (`model: haiku`, `effort: medium`, `omitClaudeMd: true`)
- implement, improve, review, re-review, and general tasks -> **main Sonnet session directly** (do NOT spawn a subagent)
- PR, merge, and image-tag bump -> `tier-haiku` subagent

Those `model` values are aliases for the latest model in each family. Do not write a versioned model ID into agent files.

Because implementation, review, and re-review stay on the main Sonnet session, all files already read stay in the main prompt cache with zero subagent round-trip.

For multi-stage prompts (such as "check log 4 agent sau đó fix nếu có issues, review & fix ok thì make PR & merge to main, sau đó bump image tag"):
1. Spawn `tier-haiku` to check the logs. If it reports no evidence of errors, stop.
2. Fix, review, and re-review directly on the main Sonnet session until clean.
3. Spawn `tier-haiku` to open/merge the PR and bump the image tag.

An explicit @-mention (`@tier-haiku`, `@tier-opus`) overrides this.
