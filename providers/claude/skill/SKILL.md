---
name: model-router
description: >
  Route each task to the Claude Code subagent pinned to the fitting model.
  Use before delegating work, and whenever the user mentions routing, which
  model, Haiku, Sonnet, Opus, check log, lên plan, fix, review, make PR, or
  bump image tag.
---

# Model router

Delegate the task to exactly one of these subagents. The subagent's `model` frontmatter pins the model. Do the work in the subagent, not on the main thread.

| Request | Subagent | Model |
| --- | --- | --- |
| Lên plan code, viết implementation plan, thiết kế cách làm | `tier-opus` | opus |
| Fix, review, sửa bug, implement | `tier-sonnet` | sonnet |
| Make PR, bump image tag, and the task is not also a fix | `tier-haiku` | haiku |
| Check log of a service to see if there are bugs, and the task is not also a fix | `tier-haiku` | haiku |
| Anything else | `tier-sonnet` | sonnet |

First match wins. A request to write a plan stays on `tier-opus` even if the plan is about a bug. A request that both fixes and opens a PR stays on `tier-sonnet`.

Examples:
- "check log của service xxx để xem có bugs ko" → `tier-haiku`
- "Fix và review" → `tier-sonnet`
- "Lên plan code" → `tier-opus`
- "Make PR & bump image tag" → `tier-haiku`

An explicit @-mention (`@tier-haiku`, `@tier-sonnet`, `@tier-opus`) overrides this table.
