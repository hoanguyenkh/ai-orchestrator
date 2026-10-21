#!/usr/bin/env python3
"""Route a Claude Code prompt across the main session and subagents.

The main session model comes from config.json. The default is Opus at high
effort. `init.sh sonnet` installs Sonnet instead. Implementation, code review,
and re-review stay on that main session in one shared context. Subagents are
only spawned for a different role:
  - plan            -> tier-opus (opus, effort high)
  - log check       -> tier-haiku (haiku)
  - PR / bump tag   -> tier-haiku (haiku)
  - implement/review/default -> main session (config mainModel)
"""

from __future__ import annotations

import json
import re
import shlex
import sys
import unicodedata
from pathlib import Path

DEFAULT_CONFIG = {
    "mainModel": "opus",
    "mainEffort": "high",
    "subagentModel": "haiku",
}
ALLOWED_MAIN_MODELS = {"opus", "sonnet"}
ALLOWED_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
ALLOWED_SUBAGENT_MODELS = {"haiku", "sonnet", "opus"}
_LABELS = {"opus": "Opus", "sonnet": "Sonnet", "haiku": "Haiku"}


def _validate_config(data: dict, *, strict: bool) -> dict:
    if data["mainModel"] not in ALLOWED_MAIN_MODELS:
        if strict:
            raise SystemExit("mainModel must be opus or sonnet")
        data["mainModel"] = DEFAULT_CONFIG["mainModel"]
    if data["mainEffort"] not in ALLOWED_EFFORTS:
        if strict:
            raise SystemExit("mainEffort must be low, medium, high, xhigh, or max")
        data["mainEffort"] = DEFAULT_CONFIG["mainEffort"]
    if data["subagentModel"] not in ALLOWED_SUBAGENT_MODELS:
        if strict:
            raise SystemExit("subagentModel must be haiku, sonnet, or opus")
        data["subagentModel"] = DEFAULT_CONFIG["subagentModel"]
    return data


def load_config_from(
    config_path: Path | None,
    settings_path: Path | None = None,
    *,
    strict: bool = False,
    settings_override: bool = False,
) -> dict:
    """Merge config.json with an optional live settings.json model."""
    data = dict(DEFAULT_CONFIG)
    if config_path is not None and config_path.is_file():
        raw = json.loads(config_path.read_text(encoding="utf-8") or "{}")
        if not isinstance(raw, dict):
            if strict:
                raise SystemExit(f"invalid config: {config_path}")
        else:
            for key in DEFAULT_CONFIG:
                if isinstance(raw.get(key), str):
                    data[key] = raw[key]
    if settings_override and settings_path is not None and settings_path.is_file():
        raw = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
        if isinstance(raw, dict):
            model = raw.get("model")
            effort = raw.get("effortLevel")
            if isinstance(model, str) and model in ALLOWED_MAIN_MODELS:
                data["mainModel"] = model
            if isinstance(effort, str) and effort in ALLOWED_EFFORTS:
                data["mainEffort"] = effort
    return _validate_config(data, strict=strict)


def load_config(*, strict: bool = False) -> dict:
    """Repo runs read config.json. The installed hook follows settings.json."""
    here = Path(__file__).resolve().parent
    local = here / "config.json"
    if local.is_file():
        return load_config_from(local, strict=strict)
    parent = here.parent
    installed = parent / "orchestrator.json"
    settings = parent / "settings.json"
    return load_config_from(
        installed if installed.is_file() else None,
        settings if settings.is_file() else None,
        strict=strict,
        settings_override=True,
    )


def resolve_install_config(main_model: str | None = None, main_effort: str | None = None) -> dict:
    data = load_config(strict=True)
    if main_model:
        data["mainModel"] = main_model
    if main_effort:
        data["mainEffort"] = main_effort
    return _validate_config(data, strict=True)


def model_label(model: str) -> str:
    return _LABELS.get(model, model)


def render_text(text: str, main_model: str, main_effort: str) -> str:
    return (
        text.replace("{{main_model}}", main_model)
        .replace("{{main_effort}}", main_effort)
        .replace("{{Main}}", model_label(main_model))
    )

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
    re.compile(r"\b(?:make|tao|mo|open|create|merge)\s+(?:a\s+)?(?:pr|pull request)\b"),
    re.compile(r"\bmerge\s+(?:to|into|vao)\s+\w+\b"),
    re.compile(r"\bgh pr\b"),
    re.compile(r"\b(?:bump|update|cap nhat|nang|doi|change)(?:\s+\w+){0,2}\s+(?:image(?:\s+tag)?|tag)\b"),
)
_LOG_RES = (
    re.compile(r"\b(?:check|kiem tra|xem|doc|read|tail)\s+(?:the\s+)?logs?(?:\s+(?:cua|\d+))?(?:\s+(?:service|agent|pod)s?)?\b"),
    re.compile(r"\breviews?\s+(?:the\s+)?(?:(?:service|agent)\s+)?logs?\b"),
    re.compile(r"\b(?:service|pod|kubectl|debug|agent)\s+logs?\b"),
    re.compile(r"\blogs?\s+(?:cua\s+)?(?:\d+\s+)?(?:service|agent|pod)s?\b"),
)
_LOG_WORD = re.compile(r"\blogs?\b")
_LOG_SIGNAL = re.compile(r"\b(?:bug|bugs|loi|error|errors|exception|exceptions|issue|issues)\b")
_SEQUENCE = re.compile(r"\b(?:roi|sau do|tiep theo|then|and then|and|va)\b")
_PURPOSE = re.compile(r"\b(?:de|cho|for|to)\b")
# Explicit cancellation in front of an intent. A trailing "không" in
# "có lỗi không" is a question particle and is not listed here.
_NEGATION_BEFORE = re.compile(
    r"(?:\bkhong can\b|\bkhong muon\b|\bkhong phai\b|\bchua can\b|"
    r"\bdung nen\b|\bdung\b|\bdon'?t\b|\bdo not\b|\bno need(?: to)?\b|"
    r"\bskip\b|\bwithout\b|\bbo qua\b)\s*$"
)
_EXPLICIT_AGENT = re.compile(r"@(?:\"|\b)(?:agent-)?(?:tier-(?:haiku|opus)|explore)\b", re.IGNORECASE)

def _stage_table(label: str) -> str:
    return (
        "- planning -> `tier-opus` subagent\n"
        "- log triage -> `tier-haiku` subagent\n"
        f"- implementation, review, and re-review -> directly on the main {label} session (do NOT spawn a subagent)\n"
        "- PR, merge, and image-tag bump -> `tier-haiku` subagent"
    )


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


def _decision(
    rule: str,
    model: str | None,
    signals: list[str],
    stages: list[dict] | None,
    agent: str | None,
) -> dict:
    return {
        "tier": model,
        "agent": agent,
        "model": model,
        "rule": rule,
        "signals": signals,
        "stages": stages,
    }


_STAGE_AGENT = {
    "plan": "tier-opus",
    "log": "tier-haiku",
    "implement": "main",
    "review": "main",
    "pr": "tier-haiku",
}


def _stage_list(names: list[str]) -> list[dict]:
    return [{"stage": name, "agent": _STAGE_AGENT[name]} for name in names]


def classify(task: str) -> dict:
    text = fold(task)
    signals = _drop_plan_subjects(text, _signals(text))
    names = _ordered_names(signals)
    main = load_config()["mainModel"]

    if set(names) and set(names).issubset({"implement", "review"}):
        rule = "fix-and-review" if len(names) == 2 else names[0]
        return _decision(rule, main, names, _stage_list(names), "main")
    if len(names) > 1 and _has_sequence_between(text, signals, names):
        return _decision("split", None, names, _stage_list(names), None)
    if len(names) > 1:
        return _decision("confirm", None, names, None, None)
    if names == ["plan"]:
        return _decision("plan", "opus", names, [{"stage": "plan", "agent": "tier-opus"}], "tier-opus")
    if names == ["log"]:
        return _decision("log-check", "haiku", names, [{"stage": "log", "agent": "tier-haiku"}], "tier-haiku")
    if names == ["pr"]:
        return _decision("pr-or-bump", "haiku", names, [{"stage": "pr", "agent": "tier-haiku"}], "tier-haiku")
    return _decision("default", main, names, [{"stage": "default", "agent": "main"}], "main")


def _format_stage(stage: dict, label: str) -> str:
    if stage["agent"] == "main":
        return f"- {stage['stage']} -> handle directly on the main {label} session (do NOT spawn a subagent)"
    return f"- {stage['stage']} -> `{stage['agent']}`"


def hook_payload(task: str) -> dict | None:
    decision = classify(task)
    if decision["agent"] == "main":
        # The main session is already the configured model. Do not inject extra tokens.
        return None
    label = model_label(load_config()["mainModel"])
    if decision["rule"] == "split":
        lines = "\n".join(_format_stage(stage, label) for stage in decision["stages"])
        context = (
            "Orchestrator hint only. Run each stage in order:\n"
            f"{lines}\n"
            f"Do `implement`, `review`, and any re-review directly on the main {label} session in this same context "
            "instead of spawning a subagent. Only spawn subagents for `tier-opus` and `tier-haiku` stages. "
            "Respect conditional gates in the prompt (e.g., 'nếu có issues', 'ok thì'): if log triage finds no evidence of errors, stop there; "
            "if review finds issues, fix and re-review on the main session before moving to the release stage. "
            "An explicit @-mention overrides this hint."
        )
    elif decision["rule"] == "confirm":
        noticed = ", ".join(decision["signals"]) or "none"
        context = (
            "Orchestrator hint only. This sentence is ambiguous. "
            f"Keyword signals noticed: {noticed}. Decide the user's intent before acting. "
            "Do not add an implement, review, log, or PR stage unless they asked for that work to be carried out. "
            "If they only want a plan, delegate only that stage to `tier-opus`. "
            "If they want several stages:\n"
            f"{_stage_table(label)}\n"
            "An explicit @-mention overrides this hint."
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


def install_hook(
    settings_path: Path,
    script_path: Path,
    main_model: str | None = None,
    main_effort: str | None = None,
) -> dict:
    cfg = resolve_install_config(main_model, main_effort)
    settings: dict = {}
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8") or "{}")
    settings["model"] = cfg["mainModel"]
    settings["effortLevel"] = cfg["mainEffort"]
    env = settings.setdefault("env", {})
    env["CLAUDE_CODE_SUBAGENT_MODEL"] = cfg["subagentModel"]
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
    orch_path = settings_path.parent / "orchestrator.json"
    orch_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return cfg


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
    out = hook_payload(stripped)
    if out is None:
        return 0
    json.dump(out, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def _pop_option(args: list[str], name: str) -> str | None:
    if name not in args:
        return None
    index = args.index(name)
    if index + 1 >= len(args):
        sys.exit(f"usage: {name} VALUE")
    value = args[index + 1]
    del args[index : index + 2]
    return value


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    main_model = _pop_option(args, "--main-model")
    main_effort = _pop_option(args, "--main-effort")
    if not args:
        return _hook_main()
    if args[0] == "--print-config":
        cfg = resolve_install_config(main_model, main_effort)
        print(f"{cfg['mainModel']} {cfg['mainEffort']} {cfg['subagentModel']}")
        return 0
    if args[0] == "--render":
        if len(args) != 3:
            sys.exit("usage: route.py --render SRC DEST [--main-model opus|sonnet]")
        cfg = resolve_install_config(main_model, main_effort)
        dest = Path(args[2])
        dest.parent.mkdir(parents=True, exist_ok=True)
        rendered = render_text(Path(args[1]).read_text(encoding="utf-8"), cfg["mainModel"], cfg["mainEffort"])
        dest.write_text(rendered, encoding="utf-8")
        return 0
    if args[0] == "--install-hook":
        if len(args) != 3:
            sys.exit("usage: route.py --install-hook SETTINGS.json SCRIPT [--main-model opus|sonnet]")
        install_hook(Path(args[1]), Path(args[2]), main_model, main_effort)
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
            "  route.py --install-hook SETTINGS.json SCRIPT [--main-model opus|sonnet]\n"
            "  route.py --print-config [--main-model opus|sonnet]\n"
            "  smoke.py                     # real Claude Code session; checks the agent that ran\n"
            "\n"
            "Main session defaults are providers/claude/config.json (opus, effort high).\n"
            "init.sh sonnet installs Sonnet instead.",
            file=sys.stderr,
        )
        return 0
    sys.exit(f"unknown argument: {args[0]}")


if __name__ == "__main__":
    sys.exit(main())
