#!/usr/bin/env python3
"""Lock the routing examples from the orchestrator policy."""

import json
import shlex
import tempfile
import unittest
from pathlib import Path

from route import classify, hook_payload, install_hook


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

    def test_fix_and_review_spawns_sonnet_twice(self):
        decision = classify("Fix và review")
        self.assertEqual(decision["agent"], "tier-sonnet")
        self.assertEqual(decision["rule"], "fix-and-review")
        self.assertEqual(
            decision["stages"],
            [
                {"stage": "implement", "agent": "tier-sonnet"},
                {"stage": "review", "agent": "tier-sonnet"},
            ],
        )

    def test_plan_is_opus(self):
        decision = classify("Lên plan code")
        self.assertEqual(decision["agent"], "tier-opus")
        self.assertEqual(decision["rule"], "plan")

    def test_plan_whose_subject_is_a_fix_stays_opus(self):
        decision = classify("lên plan để fix bug service payment")
        self.assertEqual(decision["agent"], "tier-opus")
        self.assertEqual(decision["rule"], "plan")

    def test_negated_plan_then_fix_is_sonnet(self):
        decision = classify("không cần lên plan, fix bug này")
        self.assertEqual(decision["agent"], "tier-sonnet")
        self.assertEqual(decision["rule"], "implement")
        self.assertNotIn("plan", decision["signals"])

    def test_plan_then_implement_and_pr_is_split(self):
        decision = classify("lên plan rồi implement và make PR")
        self.assertEqual(decision["rule"], "split")
        self.assertIsNone(decision["agent"])
        self.assertEqual(decision["signals"], ["plan", "implement", "pr"])

    def test_make_pr_and_bump_tag_is_haiku(self):
        decision = classify("Make Pr & bump image tag")
        self.assertEqual(decision["agent"], "tier-haiku")
        self.assertEqual(decision["rule"], "pr-or-bump")

    def test_improve_and_implement_are_sonnet(self):
        for prompt in ("improve the retry handler", "implement pagination"):
            decision = classify(prompt)
            self.assertEqual(decision["agent"], "tier-sonnet", prompt)
            self.assertEqual(decision["rule"], "implement", prompt)

    def test_review_code_is_sonnet(self):
        decision = classify("review code của service payment")
        self.assertEqual(decision["agent"], "tier-sonnet")
        self.assertEqual(decision["rule"], "review")

    def test_plan_for_a_feature_is_opus(self):
        decision = classify("plan cho tính năng refund")
        self.assertEqual(decision["agent"], "tier-opus")
        self.assertEqual(decision["rule"], "plan")

    def test_check_agent_log_is_haiku(self):
        decision = classify("check log của agent payment")
        self.assertEqual(decision["agent"], "tier-haiku")
        self.assertEqual(decision["rule"], "log-check")

    def test_agent_files_use_latest_aliases(self):
        root = Path(__file__).resolve().parent / "agents"
        expected = {
            "tier-haiku.md": "haiku",
            "tier-sonnet.md": "sonnet",
            "tier-opus.md": "opus",
        }
        for name, alias in expected.items():
            text = (root / name).read_text(encoding="utf-8")
            self.assertIn(f"model: {alias}\n", text)
            self.assertNotIn("claude-", text)

    def test_other_is_sonnet(self):
        decision = classify("thêm pagination cho orders endpoint")
        self.assertEqual(decision["agent"], "tier-sonnet")
        self.assertEqual(decision["rule"], "default")

    def test_fix_then_pr_is_split(self):
        decision = classify("fix bug rồi make PR")
        self.assertEqual(decision["rule"], "split")
        self.assertIsNone(decision["agent"])
        self.assertEqual(decision["signals"], ["implement", "pr"])

    def test_review_pr_is_sonnet(self):
        decision = classify("review the pull request")
        self.assertEqual(decision["agent"], "tier-sonnet")
        self.assertEqual(decision["rule"], "review")

    def test_log_then_fix_is_split(self):
        decision = classify("check log rồi sửa bug trong handler")
        self.assertEqual(decision["rule"], "split")
        self.assertIsNone(decision["agent"])
        self.assertEqual(decision["signals"], ["log", "implement"])

    def test_split_hook_does_not_assign_one_agent(self):
        payload = hook_payload("lên plan rồi implement và make PR")
        text = payload["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("tier-opus`", text.split("Delegate each stage")[0])
        self.assertIn("do not send it to one subagent", text)
        self.assertIn("tier-opus", text)
        self.assertIn("tier-haiku", text)
        self.assertIn("fresh tier-sonnet", text)

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
            self.assertEqual(saved["attribution"]["commit"], "")
            install_hook(settings, script)
            again = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(len(again["hooks"]["UserPromptSubmit"]), 1)
            self.assertEqual(len(again["hooks"]["UserPromptSubmit"][0]["hooks"]), 1)


if __name__ == "__main__":
    unittest.main()
