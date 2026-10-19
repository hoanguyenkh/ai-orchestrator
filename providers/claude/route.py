#!/usr/bin/env python3
"""Deterministic router for the Claude Code subagents in this repo.

Rules, first match wins:
  plan            -> tier-opus
  fix or review   -> tier-sonnet
  make PR / bump  -> tier-haiku
  check logs      -> tier-haiku
  anything else   -> tier-sonnet
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

TIERS = ("haiku", "sonnet", "opus")
AGENTS = {
    "haiku": "tier-haiku",
    "sonnet": "tier-sonnet",
    "opus": "tier-opus",
}

_PLAN_PHRASES = (
    "len plan",
    "lap plan",
    "viet plan",
    "len ke hoach",
    "ke hoach code",
    "plan code",
    "code plan",
    "implementation plan",
    "coding plan",
    "write a plan",
    "make a plan",
    "create a plan",
    "draft a plan",
    "thiet ke kien truc",
    "system design",
    "architecture plan",
)
_PLAN_RES = (
    re.compile(r"\b(write|make|create|draft)\s+(a\s+)?(code\s+|implementation\s+)?plan\b"),
    re.compile(r"\bplan\s+(the\s+)?(code|implementation|feature|refactor|migration)\b"),
)

_FIX_RES = (
    re.compile(r"\b(fix|fixes|fixing|review|reviews|reviewing|implement|implements|implementing)\b"),
    re.compile(r"\b(sua bug|sua loi|sua code|code review|fix bug)\b"),
)

_PR_PHRASES = (
    "make pr",
    "tao pr",
    "mo pr",
    "open pr",
    "open a pr",
    "create pr",
    "create a pr",
    "pull request",
    "gh pr",
    "bump image",
    "image tag",
    "bump tag",
    "cap nhat image tag",
    "bump the image",
)

_LOG_PHRASES = (
    "check log",
    "kiem tra log",
    "xem log",
    "doc log",
    "read log",
    "read the log",
    "service log",
    "pod log",
    "kubectl log",
    "debug log",
    "tail log",
)
_LOG_WORD = re.compile(r"\blogs?\b")
_LOG_SIGNAL = re.compile(r"\b(bug|bugs|loi|error|errors|exception|exceptions)\b")


def fold(text: str) -> str:
    """Lowercase and strip Vietnamese accents so 'lên' and 'len' match."""
    lowered = text.lower().replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _has_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def matches_plan(text: str) -> bool:
    return _has_phrase(text, _PLAN_PHRASES) or any(pattern.search(text) for pattern in _PLAN_RES)


def matches_fix(text: str) -> bool:
    return any(pattern.search(text) for pattern in _FIX_RES)


def matches_pr(text: str) -> bool:
    return _has_phrase(text, _PR_PHRASES)


def matches_log(text: str) -> bool:
    if _has_phrase(text, _LOG_PHRASES):
        return True
    return _LOG_WORD.search(text) is not None and _LOG_SIGNAL.search(text) is not None


def classify(task: str) -> dict:
    text = fold(task)
    if matches_plan(text):
        tier, rule = "opus", "plan"
    elif matches_fix(text):
        tier, rule = "sonnet", "fix-or-review"
    elif matches_pr(text):
        tier, rule = "haiku", "pr-or-bump"
    elif matches_log(text):
        tier, rule = "haiku", "log-check"
    else:
        tier, rule = "sonnet", "default"
    return {
        "tier": tier,
        "agent": AGENTS[tier],
        "model": tier,
        "rule": rule,
    }


def hook_payload(task: str) -> dict:
    decision = classify(task)
    context = (
        f"Orchestrator: delegate this request to the `{decision['agent']}` subagent "
        f"(model: {decision['model']}). Do the work in that subagent, not on the main thread. "
        f"Reason: {decision['rule']}. Pass the user's full request as the task. "
        f"An explicit @-mention of another subagent overrides this."
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": context,
        }
    }


def install_hook(settings_path: Path, script_path: Path) -> None:
    settings: dict = {}
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
    hooks = settings.setdefault("hooks", {})
    groups = hooks.setdefault("UserPromptSubmit", [])
    entry = {"type": "command", "command": str(script_path), "timeout": 10}
    marker = script_path.name
    replaced = False
    for group in groups:
        for hook in group.get("hooks", []):
            command = hook.get("command", "")
            args = " ".join(hook.get("args") or [])
            if marker in command or marker in args:
                hook.clear()
                hook.update(entry)
                replaced = True
    if not replaced:
        groups.append({"hooks": [entry]})
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def _read_stdin() -> str:
    if sys.stdin.isatty():
        return ""
    return sys.stdin.read()


def _hook_main() -> int:
    raw = _read_stdin().strip()
    if not raw:
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        return 0
    json.dump(hook_payload(prompt), sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _hook_main()
    if args[0] == "--install-hook":
        if len(args) != 3:
            sys.exit("usage: route.py --install-hook SETTINGS.json SCRIPT")
        install_hook(Path(args[1]), Path(args[2]))
        return 0
    if args[0] == "--explain":
        task = " ".join(args[1:]).strip() or _read_stdin().strip()
        if not task:
            sys.exit("usage: route.py --explain PROMPT")
        json.dump(classify(task), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    if args[0] in ("-h", "--help"):
        print(
            "usage:\n"
            "  route.py --explain PROMPT\n"
            "  route.py                  # Claude Code UserPromptSubmit hook (JSON on stdin)\n"
            "  route.py --install-hook SETTINGS.json SCRIPT",
            file=sys.stderr,
        )
        return 0
    sys.exit(f"unknown argument: {args[0]}")


if __name__ == "__main__":
    sys.exit(main())
