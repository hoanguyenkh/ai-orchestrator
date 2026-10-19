#!/usr/bin/env python3
"""Run one prompt in Claude Code and check which subagent actually started.

`route.py --explain` only prints the classifier. This starts `claude -p` and
looks through the stream for an Agent tool call. The main session is forced
to Sonnet for this run. A subagent model is whatever that call records; when
the call omits a model, the agent file's alias is the one Claude Code pins.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

PROMPT = "check log của service demo để xem có bugs ko"
EXPECT_AGENT = "tier-haiku"
EXPECT_MODEL = "haiku"

SYSTEM = (
    "Smoke test. Do not read files, run commands, check real logs, or edit anything. "
    "An orchestrator hint in the context names one subagent. Call the Agent tool once for that subagent. "
    "The subagent task is: reply with the single word ready and do not use tools. Then stop."
)


def _agent_calls(events: list[dict]) -> list[dict]:
    found = []
    for event in events:
        message = event.get("message") if isinstance(event, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if block.get("name") not in ("Agent", "Task"):
                continue
            raw = block.get("input")
            payload = raw if isinstance(raw, dict) else {}
            found.append(payload)
    return found


def main() -> int:
    claude = shutil.which("claude")
    if not claude:
        sys.exit("smoke: `claude` is not on PATH")

    command = [
        claude,
        "-p",
        "--model",
        "sonnet",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "dontAsk",
        "--max-budget-usd",
        "1",
        "--no-session-persistence",
        "--append-system-prompt",
        SYSTEM,
        PROMPT,
    ]
    try:
        completed = subprocess.run(command, text=True, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        sys.exit("smoke: claude -p timed out after 180s")

    events = []
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    calls = _agent_calls(events)
    print(f"prompt: {PROMPT}")
    print(f"main model requested: sonnet")
    print(f"claude exit: {completed.returncode}")
    blob = completed.stdout + completed.stderr
    if "authentication_error" in blob or "OAuth access token is invalid" in blob:
        sys.exit("smoke: Claude Code rejected the session (OAuth token invalid). Run `claude`, then /login, and run this again.")
    if not calls:
        tail = (completed.stderr or completed.stdout)[-1200:]
        sys.exit(f"smoke: no Agent tool call. Claude did not delegate.\n{tail}")

    call = calls[0]
    agent = call.get("subagent_type") or call.get("subagent") or call.get("name")
    model = call.get("model")
    print(f"agent: {agent}")
    print(f"model on the Agent call: {model or '(omitted; agent file pins ' + EXPECT_MODEL + ')'}")
    if agent != EXPECT_AGENT:
        sys.exit(f"smoke: expected {EXPECT_AGENT}, got {agent}")
    if model and model != EXPECT_MODEL:
        sys.exit(f"smoke: expected model {EXPECT_MODEL}, got {model}")
    print("smoke: pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
