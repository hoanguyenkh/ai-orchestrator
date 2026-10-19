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

A sentence that asks for several stages, such as "lên plan rồi implement và make PR", is not one Opus task. Spawn each stage on its own, even when two stages use the same model: "check log rồi make PR" is `tier-haiku` for the log, then a fresh `tier-haiku` for the PR. Respect conditional gates (`nếu có issues`, `ok thì`): stop if log triage finds no errors, and only run the final `tier-haiku` PR/merge/bump stage after the fresh `tier-sonnet` review passes.

If the wording is only a plan whose subject is a change, such as "lên kế hoạch sửa bug này", decide that before spawning. Do not add an implement stage unless the user asked for the fix to be carried out. `tier-opus` only writes the plan.

An explicit @-mention overrides this.
