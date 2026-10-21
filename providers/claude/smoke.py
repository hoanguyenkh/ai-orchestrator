#!/usr/bin/env python3
"""Run one prompt in Claude Code and check that the subagent finished.

`route.py --explain` only prints the classifier. This starts `claude -p` and
requires a successful process, a successful result event, a finished Agent
tool result, and evidence that the Haiku model ran. An Agent tool call alone
is not a pass.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

from route import load_config

PROMPT = "check log của service demo để xem có bugs ko"
EXPECT_AGENT = "tier-haiku"
EXPECT_MODEL = "haiku"

SYSTEM = (
    "Smoke test. Do not read files, run commands, check real logs, or edit anything. "
    "An orchestrator hint in the context names one subagent. Call the Agent tool once for that subagent. "
    "The subagent task is: reply with the single word ready and do not use tools. Then stop."
)


def _blocks(event: dict) -> list:
    message = event.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), list):
        return message["content"]
    content = event.get("content")
    return content if isinstance(content, list) else []


def evaluate_session(returncode: int, events: list[dict]) -> str | None:
    """Return an error, or None when the session shows Haiku finished the task."""
    if returncode != 0:
        return f"claude exit {returncode}"

    calls = []
    results = []
    final = None
    usage_names: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("type") == "result":
            final = event
        usage = event.get("modelUsage")
        if isinstance(usage, dict):
            usage_names.extend(str(name).lower() for name in usage)
        message = event.get("message")
        if isinstance(message, dict) and event.get("parent_tool_use_id") and message.get("model"):
            usage_names.append(str(message["model"]).lower())
        for block in _blocks(event):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task"):
                raw = block.get("input")
                calls.append({"id": block.get("id"), "input": raw if isinstance(raw, dict) else {}})
            elif block.get("type") == "tool_result":
                results.append(block)

    if final is None or final.get("is_error") or final.get("subtype") != "success":
        return "no successful result event"
    if any(block.get("is_error") for block in results):
        return "a tool result reported an error"
    if not calls:
        return "no Agent tool call"

    call = calls[0]
    agent = call["input"].get("subagent_type") or call["input"].get("subagent") or call["input"].get("name")
    if agent != EXPECT_AGENT:
        return f"expected {EXPECT_AGENT}, got {agent}"
    if not call["id"]:
        return "Agent call has no id, so its result cannot be checked"
    matched = [block for block in results if block.get("tool_use_id") == call["id"]]
    if not matched:
        return "Agent call has no tool result, so the agent did not finish"
    if any(block.get("is_error") for block in matched):
        return "Agent tool result reported an error"

    model = call["input"].get("model")
    model_text = model.lower() if isinstance(model, str) else ""
    if EXPECT_MODEL not in model_text and not any(EXPECT_MODEL in name for name in usage_names):
        return "stream does not show that the agent finished on haiku"
    return None


def main() -> int:
    claude = shutil.which("claude")
    if not claude:
        sys.exit("smoke: `claude` is not on PATH")
    main_model = load_config()["mainModel"]

    command = [
        claude,
        "-p",
        "--model",
        main_model,
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
        "Agent",
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

    print(f"prompt: {PROMPT}")
    print(f"main model requested: {main_model}")
    print(f"claude exit: {completed.returncode}")
    blob = completed.stdout + completed.stderr
    if "authentication_error" in blob or "OAuth access token is invalid" in blob:
        sys.exit("smoke: Claude Code rejected the session (OAuth token invalid). Run `claude`, then /login, and run this again.")
    error = evaluate_session(completed.returncode, events)
    if error:
        tail = (completed.stderr or completed.stdout)[-1200:]
        sys.exit(f"smoke: {error}\n{tail}")
    print("smoke: pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
