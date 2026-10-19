---
name: model-router
description: >
  Split a request into stages and delegate each stage to the Claude Code
  subagent pinned to the fitting model. Use before delegating work, and
  whenever the user mentions routing, which model, Haiku, Sonnet, Opus,
  check log, lên plan, fix, review, make PR, or bump image tag.
---

# Model router

The main session stays on Sonnet and coordinates. It does not do the stage work itself. A hook hint is context, not a model switch: you still have to call the Agent tool.

Route each stage separately:

- plan code or plan a feature -> `tier-opus` (`model: opus`, the latest Opus alias)
- check logs of a service or an agent -> `tier-haiku` (`model: haiku`, the latest Haiku alias)
- implement or improve -> a fresh `tier-sonnet` (`model: sonnet`, the latest Sonnet alias)
- review code -> another fresh `tier-sonnet`
- PR and image-tag bump -> `tier-haiku`

Those `model` values are aliases. When Sonnet 5.8 or a later Haiku or Opus ships, leave the alias. Do not write a versioned id into the agent file.

Fix and review share the `tier-sonnet` definition. Spawn it twice so the reviewer does not see the implementer's context.

A clear one-stage request goes to that one subagent. "Lên plan để fix bug" is a plan whose subject is the bug, so only `tier-opus` runs. "Không cần lên plan, fix bug này" drops the negated plan and only implements. "Review log ... xem có lỗi không" is log triage on `tier-haiku`, not a code review.

A sentence that asks for several stages, such as "lên plan rồi implement và make PR", is not one Opus task. Read it, skip stages the user negated, delegate each remaining stage, and finish all of them. `tier-opus` only writes the plan.

An explicit @-mention overrides this.
