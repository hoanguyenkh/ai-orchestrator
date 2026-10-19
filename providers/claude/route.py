#!/usr/bin/env python3
"""Route a Claude Code prompt to subagents.

Clear, single-intent requests get one suggested subagent. A negated intent is
dropped, so "không cần lên plan, fix bug này" stays a fix. Two or more stages
split in the order they appear, even when they share a model, so "check log
rồi make PR" is two Haiku spawns. Several signals without a sequence word
between them are "confirm": the main Sonnet session decides the intent before
any extra stage runs.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
import unicodedata
from pathlib import Path

AGENTS = {
    "haiku": "tier-haiku",
    "sonnet": "tier-sonnet",
    "opus": "tier-opus",
}

_SIGNAL_ORDER = ("plan", "log", "implement", "review", "pr")

_PLAN_RES = (
    re.compile(r"\blen plan\b"),
    re.compile(r"\blap plan\b"),
    re.compile(r"\bviet plan\b"),
    re.compile(r"\blen ke hoach\b"),
    re.compile(r"\bke hoach code\b"),
    re.compile(r"\bplan code\b"),
    re.compile(r"\bcode plan\b"),
    re.compile(r"\bimplementation plan\b"),
    re.compile(r"\bcoding plan\b"),
    re.compile(r"\b(?:write|make|create|draft)\s+(?:a\s+)?(?:code\s+|implementation\s+)?plan\b"),
    re.compile(r"\bplan\s+(?:the\s+)?(?:code|implementation|feature|refactor|migration)\b"),
    re.compile(r"\bplan\s+(?:cho|for)\s+(?:tinh nang|feature|a feature|the feature)\b"),
    re.compile(r"\bthiet ke kien truc\b"),
    re.compile(r"\bsystem design\b"),
    re.compile(r"\barchitecture plan\b"),
)
_IMPLEMENT_RE = re.compile(
    r"\b(?:"
    r"fix(?:\s+(?:the\s+)?(?:bugs?|errors?|exceptions?))?|"
    r"fixes|fixing|implement|implements|implementing|"
    r"improve|improves|improving|improvement|"
    r"cai thien|sua bug|sua loi|sua code"
    r")\b"
)
_REVIEW_RE = re.compile(r"\b(?:reviews?|reviewing|code review)\b")
_REVIEW_LOG_RE = re.compile(r"\breviews?\s+(?:the\s+)?(?:(?:service|agent)\s+)?logs?\b")
_PR_RES = (
    re.compile(r"\b(?:make|tao|mo|open|create)\s+(?:a\s+)?pr\b"),
    re.compile(r"\b(?:make|tao|mo|open|create)\s+(?:a\s+)?pull request\b"),
    re.compile(r"\bgh pr\b"),
    re.compile(r"\b(?:bump|update|cap nhat|nang|doi|change)(?:\s+\w+){0,2}\s+(?:image(?:\s+tag)?|tag)\b"),
)
_LOG_RES = (
    re.compile(r"\bcheck logs?\b"),
    re.compile(r"\bkiem tra logs?\b"),
    re.compile(r"\bxem logs?\b"),
    re.compile(r"\bdoc logs?\b"),
    re.compile(r"\bread(?:\s+the)?\s+logs?\b"),
    re.compile(r"\breviews?\s+(?:the\s+)?(?:(?:service|agent)\s+)?logs?\b"),
    re.compile(r"\bservice logs?\b"),
    re.compile(r"\bpod logs?\b"),
    re.compile(r"\bkubectl logs?\b"),
    re.compile(r"\bdebug logs?\b"),
    re.compile(r"\btail logs?\b"),
    re.compile(r"\blogs?\s+cua\s+(?:service|agent)\b"),
    re.compile(r"\bagent logs?\b"),
)
_LOG_WORD = re.compile(r"\blogs?\b")
_LOG_SIGNAL = re.compile(r"\b(?:bug|bugs|loi|error|errors|exception|exceptions)\b")
_SEQUENCE = re.compile(r"\b(?:roi|sau do|tiep theo|then|and then|and|va)\b")
_PURPOSE = re.compile(r"\b(?:de|cho|for|to)\b")
# Explicit cancellation in front of an intent. A trailing "không" in
# "có lỗi không" is a question particle and is not listed here.
_NEGATION_BEFORE = re.compile(
    r"(?:\bkhong can\b|\bkhong muon\b|\bkhong phai\b|\bchua can\b|"
    r"\bdung nen\b|\bdung\b|\bdon'?t\b|\bdo not\b|\bno need(?: to)?\b|"
    r"\bskip\b|\bwithout\b|\bbo qua\b)\s*$"
)
_EXPLICIT_AGENT = re.compile(r"@(?:\"|\b)(?:agent-)?tier-(?:haiku|sonnet|opus)\b", re.IGNORECASE)

_STAGE_TABLE = """\
- planning -> tier-opus
- log triage -> tier-haiku
- implementation -> a fresh tier-sonnet
- independent review -> another fresh tier-sonnet, separate from the implementer
- PR and image-tag bump -> tier-haiku"""


def fold(text: str) -> str:
    """Lowercase and strip Vietnamese accents so 'lên' and 'len' match."""
    lowered = text.lower().replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", lowered)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _spans(pattern: re.Pattern[str], text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in pattern.finditer(text)]


def _overlaps(span: tuple[int, int], others: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(not (end <= other_start or start >= other_end) for other_start, other_end in others)


def _negated(text: str, start: int) -> bool:
    window = text[max(0, start - 48) : start]
    return _NEGATION_BEFORE.search(window) is not None


def _live(text: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    return [span for span in spans if not _negated(text, span[0])]


def _signals(text: str) -> dict[str, list[tuple[int, int]]]:
    review_log = _spans(_REVIEW_LOG_RE, text)
    review = [span for span in _spans(_REVIEW_RE, text) if not _overlaps(span, review_log)]
    implement = _live(text, _spans(_IMPLEMENT_RE, text))

    log = []
    for pattern in _LOG_RES:
        log.extend(_spans(pattern, text))
    log = _live(text, log)
    if not log:
        log_words = _live(text, _spans(_LOG_WORD, text))
        log_errors = [
            span
            for span in _live(text, _spans(_LOG_SIGNAL, text))
            if not _overlaps(span, implement)
        ]
        if log_words and log_errors:
            log.append(log_words[0])

    found = {
        "plan": _live(text, [span for pattern in _PLAN_RES for span in _spans(pattern, text)]),
        "log": log,
        "implement": implement,
        "review": _live(text, review),
        "pr": _live(text, [span for pattern in _PR_RES for span in _spans(pattern, text)]),
    }
    return {name: spans for name, spans in found.items() if spans}


def _drop_plan_subjects(text: str, signals: dict[str, list[tuple[int, int]]]) -> dict[str, list[tuple[int, int]]]:
    """Drop spans after 'plan' that are attached with 'để/cho/for/to' and no sequence word."""
    if "plan" not in signals or len(signals) < 2:
        return signals
    plan_end = min(end for _, end in signals["plan"])
    trimmed: dict[str, list[tuple[int, int]]] = {"plan": signals["plan"]}
    for name, spans in signals.items():
        if name == "plan":
            continue
        kept = []
        for start, end in spans:
            between = text[plan_end:start] if start >= plan_end else ""
            if start >= plan_end and _PURPOSE.search(between) and not _SEQUENCE.search(between):
                continue
            kept.append((start, end))
        if kept:
            trimmed[name] = kept
    return trimmed


def _ordered_names(signals: dict[str, list[tuple[int, int]]]) -> list[str]:
    return sorted(
        signals,
        key=lambda name: (min(start for start, _ in signals[name]), _SIGNAL_ORDER.index(name)),
    )


def _has_sequence_between(text: str, signals: dict[str, list[tuple[int, int]]], names: list[str]) -> bool:
    if len(names) < 2:
        return False
    first_end = min(end for _, end in signals[names[0]])
    last_start = max(start for start, _ in signals[names[-1]])
    if last_start <= first_end:
        return False
    return _SEQUENCE.search(text[first_end:last_start]) is not None


def _decision(rule: str, tier: str | None, signals: list[str], stages: list[dict] | None) -> dict:
    return {
        "tier": tier,
        "agent": AGENTS[tier] if tier else None,
        "model": tier,
        "rule": rule,
        "signals": signals,
        "stages": stages,
    }


_STAGE_AGENT = {
    "plan": "tier-opus",
    "log": "tier-haiku",
    "implement": "tier-sonnet",
    "review": "tier-sonnet",
    "pr": "tier-haiku",
}


def _stage_list(names: list[str]) -> list[dict]:
    return [{"stage": name, "agent": _STAGE_AGENT[name]} for name in names]


def classify(task: str) -> dict:
    text = fold(task)
    signals = _drop_plan_subjects(text, _signals(text))
    names = _ordered_names(signals)

    if names == ["implement", "review"]:
        return _decision("fix-and-review", "sonnet", names, _stage_list(names))
    if len(names) > 1 and _has_sequence_between(text, signals, names):
        return _decision("split", None, names, _stage_list(names))
    if len(names) > 1:
        return _decision("confirm", None, names, None)
    if names == ["plan"]:
        return _decision("plan", "opus", names, [{"stage": "plan", "agent": "tier-opus"}])
    if names == ["log"]:
        return _decision("log-check", "haiku", names, [{"stage": "log", "agent": "tier-haiku"}])
    if names == ["pr"]:
        return _decision("pr-or-bump", "haiku", names, [{"stage": "pr", "agent": "tier-haiku"}])
    if names == ["implement"]:
        return _decision("implement", "sonnet", names, [{"stage": "implement", "agent": "tier-sonnet"}])
    if names == ["review"]:
        return _decision("review", "sonnet", names, [{"stage": "review", "agent": "tier-sonnet"}])
    return _decision("default", "sonnet", names, [{"stage": "default", "agent": "tier-sonnet"}])


def hook_payload(task: str) -> dict:
    decision = classify(task)
    if decision["rule"] == "split":
        lines = "\n".join(f"- {stage['stage']} -> `{stage['agent']}`" for stage in decision["stages"])
        context = (
            "Orchestrator hint only. These are separate stages, even when they use the same model. "
            "Do not send the whole request to one subagent. Spawn each stage on its own:\n"
            f"{lines}\n"
            "Finish every stage. An explicit @-mention overrides this hint."
        )
    elif decision["rule"] == "confirm":
        noticed = ", ".join(decision["signals"]) or "none"
        context = (
            "Orchestrator hint only. This sentence is ambiguous. "
            f"Keyword signals noticed: {noticed}. Decide the user's intent before spawning any subagent. "
            "Do not add an implement, review, log, or PR stage unless they asked for that work to be carried out. "
            "If they only want a plan, delegate only that stage to `tier-opus`. "
            "If they want several stages, spawn each one separately:\n"
            f"{_STAGE_TABLE}\n"
            "An explicit @-mention overrides this hint."
        )
    elif decision["rule"] == "fix-and-review":
        context = (
            "Orchestrator hint only. Spawn `tier-sonnet` twice. "
            "The first spawn implements the fix. The second spawn is a fresh reviewer with its own context and only reviews. "
            "Do not let the implementer review its own change. An explicit @-mention overrides this hint."
        )
    else:
        context = (
            f"Orchestrator hint only. This looks like one {decision['rule']} stage. "
            f"Delegate it to `{decision['agent']}` (model: {decision['model']}) and do the work in that subagent. "
            "An explicit @-mention overrides this hint."
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
    settings["model"] = "sonnet"
    hooks = settings.setdefault("hooks", {})
    groups = hooks.setdefault("UserPromptSubmit", [])
    entry = {"type": "command", "command": shlex.quote(str(script_path)), "timeout": 10}
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
    if not isinstance(prompt, str):
        return 0
    stripped = prompt.strip()
    if not stripped or stripped.startswith("/") or _EXPLICIT_AGENT.search(stripped):
        return 0
    json.dump(hook_payload(stripped), sys.stdout, ensure_ascii=False)
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
            "  route.py --explain PROMPT    # classifier only; does not run a model\n"
            "  route.py                     # Claude Code UserPromptSubmit hook\n"
            "  route.py --install-hook SETTINGS.json SCRIPT\n"
            "  smoke.py                     # real Claude Code session; checks the agent that ran",
            file=sys.stderr,
        )
        return 0
    sys.exit(f"unknown argument: {args[0]}")


if __name__ == "__main__":
    sys.exit(main())
