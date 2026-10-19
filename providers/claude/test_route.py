#!/usr/bin/env python3
"""Lock the routing examples from the orchestrator policy."""

import io
import json
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from route import classify, hook_payload, install_hook, main as route_main
from smoke import evaluate_session


class RouteTests(unittest.TestCase):
    def test_log_check_is_haiku(self):
        decision = classify("check log của service xxx để xem có bugs ko")
        self.assertEqual(decision["agent"], "tier-haiku")
        self.assertEqual(decision["rule"], "log-check")

    def test_log_check_without_accents(self):
        decision = classify("kiem tra log service payment co bug khong")
        self.assertEqual(decision["agent"], "tier-haiku")
        self.assertEqual(decision["rule"], "log-check")

    def test_review_log_is_haiku_not_code_review(self):
        decision = classify("review log service payment xem có lỗi không")
        self.assertEqual(decision["agent"], "tier-haiku")
        self.assertEqual(decision["rule"], "log-check")

    def test_fix_and_review_stays_on_main_sonnet_session(self):
        decision = classify("Fix và review")
        self.assertEqual(decision["agent"], "main")
        self.assertEqual(decision["model"], "sonnet")
        self.assertEqual(decision["rule"], "fix-and-review")
        self.assertEqual(
            decision["stages"],
            [
                {"stage": "implement", "agent": "main"},
                {"stage": "review", "agent": "main"},
            ],
        )
        self.assertIsNone(hook_payload("Fix và review"))

    def test_plan_is_opus(self):
        decision = classify("Lên plan code")
        self.assertEqual(decision["agent"], "tier-opus")
        self.assertEqual(decision["rule"], "plan")

    def test_plan_whose_subject_is_a_fix_stays_opus(self):
        decision = classify("lên plan để fix bug service payment")
        self.assertEqual(decision["agent"], "tier-opus")
        self.assertEqual(decision["rule"], "plan")

    def test_negated_plan_then_fix_is_main_sonnet(self):
        decision = classify("không cần lên plan, fix bug này")
        self.assertEqual(decision["agent"], "main")
        self.assertEqual(decision["model"], "sonnet")
        self.assertEqual(decision["rule"], "implement")
        self.assertNotIn("plan", decision["signals"])
        self.assertIsNone(hook_payload("không cần lên plan, fix bug này"))

    def test_plan_then_implement_and_pr_is_split(self):
        decision = classify("lên plan rồi implement và make PR")
        self.assertEqual(decision["rule"], "split")
        self.assertIsNone(decision["agent"])
        self.assertEqual(decision["signals"], ["plan", "implement", "pr"])
        self.assertEqual(
            decision["stages"],
            [
                {"stage": "plan", "agent": "tier-opus"},
                {"stage": "implement", "agent": "main"},
                {"stage": "pr", "agent": "tier-haiku"},
            ],
        )

    def test_log_then_pr_is_two_haiku_stages(self):
        decision = classify("check log rồi make PR")
        self.assertEqual(decision["rule"], "split")
        self.assertIsNone(decision["agent"])
        self.assertEqual(
            decision["stages"],
            [
                {"stage": "log", "agent": "tier-haiku"},
                {"stage": "pr", "agent": "tier-haiku"},
            ],
        )

    def test_log_then_bump_tag_is_two_haiku_stages(self):
        decision = classify("check log service payment rồi bump image tag")
        self.assertEqual(decision["rule"], "split")
        self.assertIsNone(decision["agent"])
        self.assertEqual(
            decision["stages"],
            [
                {"stage": "log", "agent": "tier-haiku"},
                {"stage": "pr", "agent": "tier-haiku"},
            ],
        )

    def test_plan_wording_without_a_sequence_asks_before_acting(self):
        decision = classify("lên kế hoạch sửa bug này")
        self.assertEqual(decision["rule"], "confirm")
        self.assertIsNone(decision["agent"])
        self.assertEqual(decision["signals"], ["plan", "implement"])
        text = hook_payload("lên kế hoạch sửa bug này")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Decide the user's intent before acting", text)
        self.assertIn("Do not add an implement", text)

    def test_make_pr_and_bump_tag_is_haiku(self):
        decision = classify("Make Pr & bump image tag")
        self.assertEqual(decision["agent"], "tier-haiku")
        self.assertEqual(decision["rule"], "pr-or-bump")

    def test_improve_and_implement_stay_on_main_sonnet(self):
        for prompt in ("improve the retry handler", "implement pagination"):
            decision = classify(prompt)
            self.assertEqual(decision["agent"], "main", prompt)
            self.assertEqual(decision["model"], "sonnet", prompt)
            self.assertEqual(decision["rule"], "implement", prompt)
            self.assertIsNone(hook_payload(prompt))

    def test_review_code_stays_on_main_sonnet(self):
        decision = classify("review code của service payment")
        self.assertEqual(decision["agent"], "main")
        self.assertEqual(decision["model"], "sonnet")
        self.assertEqual(decision["rule"], "review")
        self.assertIsNone(hook_payload("review code của service payment"))

    def test_plan_for_a_feature_is_opus(self):
        decision = classify("plan cho tính năng refund")
        self.assertEqual(decision["agent"], "tier-opus")
        self.assertEqual(decision["rule"], "plan")

    def test_check_agent_log_is_haiku(self):
        decision = classify("check log của agent payment")
        self.assertEqual(decision["agent"], "tier-haiku")
        self.assertEqual(decision["rule"], "log-check")

    def test_agent_files_use_latest_aliases_and_fast_haiku_settings(self):
        root = Path(__file__).resolve().parent / "agents"
        expected = {
            "tier-haiku.md": "haiku",
            "tier-opus.md": "opus",
            "Explore.md": "haiku",
        }
        self.assertFalse((root / "tier-sonnet.md").exists())
        for name, alias in expected.items():
            text = (root / name).read_text(encoding="utf-8")
            self.assertIn(f"model: {alias}\n", text)
            self.assertIn("disallowedTools:", text)
            self.assertIn("Agent", text)
            self.assertNotIn("claude-", text)
        haiku_text = (root / "tier-haiku.md").read_text(encoding="utf-8")
        self.assertIn("effort: medium\n", haiku_text)
        self.assertIn("maxTurns: 15\n", haiku_text)
        self.assertIn("omitClaudeMd: true\n", haiku_text)

    def test_other_stays_on_main_sonnet(self):
        decision = classify("thêm pagination cho orders endpoint")
        self.assertEqual(decision["agent"], "main")
        self.assertEqual(decision["model"], "sonnet")
        self.assertEqual(decision["rule"], "default")
        self.assertIsNone(hook_payload("thêm pagination cho orders endpoint"))

    def test_fix_then_pr_is_split(self):
        decision = classify("fix bug rồi make PR")
        self.assertEqual(decision["rule"], "split")
        self.assertIsNone(decision["agent"])
        self.assertEqual(decision["signals"], ["implement", "pr"])

    def test_review_pr_stays_on_main_sonnet(self):
        decision = classify("review the pull request")
        self.assertEqual(decision["agent"], "main")
        self.assertEqual(decision["rule"], "review")

    def test_log_then_fix_is_split(self):
        decision = classify("check log rồi sửa bug trong handler")
        self.assertEqual(decision["rule"], "split")
        self.assertIsNone(decision["agent"])
        self.assertEqual(decision["signals"], ["log", "implement"])

    def test_split_hook_lists_each_stage(self):
        text = hook_payload("lên plan rồi implement và make PR")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("- plan -> `tier-opus`", text)
        self.assertIn("- implement -> handle directly on the main Sonnet session", text)
        self.assertIn("- pr -> `tier-haiku`", text)

    def test_same_model_split_hook_spawns_haiku_twice(self):
        text = hook_payload("check log rồi make PR")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("- log -> `tier-haiku`", text)
        self.assertIn("- pr -> `tier-haiku`", text)

    def test_stages_follow_prompt_order(self):
        decision = classify("check log rồi lên plan")
        self.assertEqual(decision["rule"], "split")
        self.assertEqual(
            decision["stages"],
            [
                {"stage": "log", "agent": "tier-haiku"},
                {"stage": "plan", "agent": "tier-opus"},
            ],
        )

    def test_trailing_and_does_not_turn_ambiguous_plan_into_split(self):
        decision = classify("lên kế hoạch sửa bug cho service A và service B")
        self.assertEqual(decision["rule"], "confirm")
        self.assertIsNone(decision["agent"])

    def test_plan_to_fix_Then_pr_drops_only_the_plan_subject(self):
        decision = classify("lên plan để fix bug rồi make PR")
        self.assertEqual(decision["rule"], "split")
        self.assertEqual(
            decision["stages"],
            [
                {"stage": "plan", "agent": "tier-opus"},
                {"stage": "pr", "agent": "tier-haiku"},
            ],
        )

    def test_fixing_log_code_or_image_tag_code_stays_sonnet(self):
        for prompt in ("sửa lỗi không ghi log", "fix bug parse sai image tag"):
            decision = classify(prompt)
            self.assertEqual(decision["agent"], "main", prompt)
            self.assertEqual(decision["rule"], "implement", prompt)

    def test_conditional_log_fix_review_pr_bump_pipeline(self):
        prompt = "check log 4 agent sau đó fix nếu có issues, review & fix ok thì make PR & merge to main, sau đó bump image tag to xxxx"
        decision = classify(prompt)
        self.assertEqual(decision["rule"], "split")
        self.assertEqual(
            decision["stages"],
            [
                {"stage": "log", "agent": "tier-haiku"},
                {"stage": "implement", "agent": "main"},
                {"stage": "review", "agent": "main"},
                {"stage": "pr", "agent": "tier-haiku"},
            ],
        )
        text = hook_payload(prompt)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Respect conditional gates", text)
        self.assertIn("directly on the main Sonnet session", text)

    def test_hook_stays_silent_on_slash_commands_mentions_and_pure_sonnet(self):
        for prompt in ("/agents", "@tier-haiku fix this", "@agent-tier-opus check log", "Fix và review"):
            stdin = io.StringIO(json.dumps({"prompt": prompt}))
            stdout = io.StringIO()
            with patch("sys.stdin", stdin), patch("sys.stdout", stdout):
                self.assertEqual(route_main([]), 0)
            self.assertEqual(stdout.getvalue(), "", prompt)

    def test_install_hook_quotes_paths_and_sets_main_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "settings.json"
            settings.write_text('{"attribution": {"commit": ""}}\n', encoding="utf-8")
            script = root / "Test User" / "orchestrator-route.py"
            install_hook(settings, script)
            saved = json.loads(settings.read_text(encoding="utf-8"))
            command = saved["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
            self.assertEqual(command, shlex.quote(str(script)))
            self.assertTrue(command.startswith("'"))
            self.assertEqual(saved["model"], "sonnet")
            self.assertEqual(saved["env"]["CLAUDE_CODE_SUBAGENT_MODEL"], "haiku")
            self.assertEqual(saved["attribution"]["commit"], "")
            install_hook(settings, script)
            again = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(len(again["hooks"]["UserPromptSubmit"]), 1)
            self.assertEqual(len(again["hooks"]["UserPromptSubmit"][0]["hooks"]), 1)


def _agent_call(model="haiku"):
    payload = {"subagent_type": "tier-haiku"}
    if model is not None:
        payload["model"] = model
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "Agent", "id": "call-1", "input": payload}]},
    }


def _tool_result(is_error=False):
    return {
        "type": "user",
        "message": {
            "content": [{"type": "tool_result", "tool_use_id": "call-1", "is_error": is_error, "content": "ready"}]
        },
    }


def _result(is_error=False):
    return {"type": "result", "subtype": "success", "is_error": is_error, "result": "ready"}


class SmokeEvaluationTests(unittest.TestCase):
    def test_exit_code_and_failed_result_do_not_pass(self):
        events = [_agent_call(), _result(is_error=True)]
        self.assertEqual(evaluate_session(1, events), "claude exit 1")

    def test_successful_exit_with_an_error_result_does_not_pass(self):
        events = [_agent_call(), _tool_result(), _result(is_error=True)]
        self.assertEqual(evaluate_session(0, events), "no successful result event")

    def test_tool_result_error_does_not_pass(self):
        events = [_agent_call(), _tool_result(is_error=True), _result()]
        self.assertEqual(evaluate_session(0, events), "a tool result reported an error")

    def test_agent_call_without_a_finished_result_does_not_pass(self):
        events = [_agent_call(), _result()]
        self.assertIn("did not finish", evaluate_session(0, events))

    def test_missing_model_evidence_does_not_pass(self):
        events = [_agent_call(model=None), _tool_result(), _result()]
        self.assertIn("finished on haiku", evaluate_session(0, events))

    def test_finished_haiku_call_passes(self):
        events = [_agent_call(), _tool_result(), _result()]
        self.assertIsNone(evaluate_session(0, events))

    def test_model_usage_can_prove_haiku_ran(self):
        events = [_agent_call(model=None), _tool_result(), _result(), {"type": "result", "subtype": "success", "is_error": False, "modelUsage": {"claude-haiku-4-5": {}}}]
        self.assertIsNone(evaluate_session(0, events))


if __name__ == "__main__":
    unittest.main()
