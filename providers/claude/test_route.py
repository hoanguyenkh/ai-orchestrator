#!/usr/bin/env python3
"""Lock the routing examples from the orchestrator policy."""

import io
import json
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from route import (
    classify,
    hook_payload,
    install_hook,
    load_config,
    load_config_from,
    render_text,
    main as route_main,
)
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

    def test_fix_and_review_stays_on_main_opus_session(self):
        decision = classify("Fix và review")
        self.assertEqual(decision["agent"], "main")
        self.assertEqual(decision["model"], "opus")
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
        self.assertEqual(decision["agent"], "tier-plan")
        self.assertEqual(decision["rule"], "plan")

    def test_plan_whose_subject_is_a_fix_stays_opus(self):
        decision = classify("lên plan để fix bug service payment")
        self.assertEqual(decision["agent"], "tier-plan")
        self.assertEqual(decision["rule"], "plan")

    def test_negated_plan_then_fix_is_main_opus(self):
        decision = classify("không cần lên plan, fix bug này")
        self.assertEqual(decision["agent"], "main")
        self.assertEqual(decision["model"], "opus")
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
                {"stage": "plan", "agent": "tier-plan"},
                {"stage": "implement", "agent": "main"},
                {"stage": "pr", "agent": "tier-haiku-release"},
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
                {"stage": "pr", "agent": "tier-haiku-release"},
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
                {"stage": "bump", "agent": "tier-haiku-release"},
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

    def test_make_pr_and_bump_tag_is_one_release_call(self):
        decision = classify("Make Pr & bump image tag")
        self.assertEqual(decision["rule"], "split")
        self.assertIsNone(decision["agent"])
        self.assertEqual(decision["signals"], ["pr", "bump"])
        self.assertEqual(
            decision["stages"],
            [{"stage": "release", "agent": "tier-haiku-release"}],
        )
        text = hook_payload("Make Pr & bump image tag")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("in ONE call (do not spawn it twice)", text)
        self.assertNotIn("- bump ->", text)
        # The release stage still carries the pull request follow-up.
        self.assertIn("The prompt does not ask to merge, so do not merge.", text)

    def test_a_requested_merge_keeps_the_bump_after_the_pr(self):
        decision = classify("make PR & merge to main, sau đó bump image tag")
        self.assertEqual(
            decision["stages"],
            [
                {"stage": "pr", "agent": "tier-haiku-release"},
                {"stage": "bump", "agent": "tier-haiku-release"},
            ],
        )
        text = hook_payload("make PR & merge to main, sau đó bump image tag")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("The prompt asks to merge.", text)
        self.assertNotIn("- release ->", text)
        self.assertLess(text.index("- pr ->"), text.index("- bump ->"))

    def test_a_bump_before_the_pr_is_not_folded(self):
        decision = classify("bump image tag rồi make PR")
        self.assertEqual(
            [stage["stage"] for stage in decision["stages"]],
            ["bump", "pr"],
        )

    def test_a_bump_separated_from_the_pr_is_not_folded(self):
        decision = classify("make PR rồi fix the retry handler rồi bump image tag")
        self.assertEqual(
            [stage["stage"] for stage in decision["stages"]],
            ["pr", "implement", "bump"],
        )

    def test_git_commit_is_haiku(self):
        decision = classify("git commit the retry handler")
        self.assertEqual(decision["agent"], "tier-haiku-release")
        self.assertEqual(decision["rule"], "commit")

    def test_fix_then_commit_splits_before_the_commit_word(self):
        decision = classify("fix rồi commit")
        self.assertEqual(decision["rule"], "split")
        self.assertEqual(
            [stage["stage"] for stage in decision["stages"]],
            ["implement", "commit"],
        )

    def test_commit_to_a_plan_is_not_a_commit_stage(self):
        decision = classify("commit to the refund plan")
        self.assertNotIn("commit", decision["signals"])
        self.assertEqual(decision["agent"], "main")

    def test_make_pr_is_one_release_stage_with_the_push(self):
        decision = classify("make a PR")
        self.assertEqual(decision["agent"], "tier-haiku-release")
        self.assertEqual(decision["rule"], "pr")
        text = hook_payload("make a PR")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("commits, pushes, and opens the pull request in one stage", text)
        self.assertIn("never lands without the push that the pull request needs", text)
        self.assertNotIn("The prompt asks to merge.", text)
        self.assertIn("The prompt does not ask to merge, so do not merge.", text)

    def test_make_pr_and_merge_keeps_the_merge_on_the_release_stage(self):
        text = hook_payload("make PR & merge to main")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("- pr -> `tier-haiku-release`", text)
        self.assertIn("The prompt asks to merge.", text)
        self.assertIn("`tier-haiku-release` merges after the pull request is open.", text)

    def test_a_bare_merge_word_is_not_a_merge_request(self):
        for prompt in (
            "fix the merge conflict then make a PR",
            "resolve merge conflicts rồi make pr",
            "xem lại merge strategy rồi make pr",
            "make a PR, do not merge",
            "make a PR, đừng merge",
            "make a PR, không merge nhé",
            "make a PR without merging",
        ):
            text = hook_payload(prompt)["hookSpecificOutput"]["additionalContext"]
            self.assertNotIn("The prompt asks to merge.", text, prompt)
            self.assertIn("so do not merge", text, prompt)

    def test_an_explicit_merge_request_is_still_seen(self):
        for prompt in ("make PR & merge to main", "make a pr then merge the PR", "mở PR rồi merge vào main"):
            text = hook_payload(prompt)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("The prompt asks to merge.", text, prompt)

    def test_a_question_about_git_is_not_a_commit_request(self):
        for prompt in (
            "explain git commit vs git stash",
            "how do I git commit?",
            "what does git commit do",
            "giải thích git commit",
            "so sánh git commit và git stash",
        ):
            decision = classify(prompt)
            self.assertNotIn("commit", decision["signals"], prompt)
            self.assertEqual(decision["agent"], "main", prompt)
            self.assertIsNone(hook_payload(prompt), prompt)

    def test_a_commit_after_a_question_sentence_is_still_a_commit(self):
        decision = classify("what broke here? then git commit the fix")
        self.assertIn("commit", decision["signals"])

    def test_commit_word_is_not_a_commit_request(self):
        for prompt in (
            "fix the commit parser",
            "sửa lỗi commit",
            "show the commit history",
            "revert the last commit",
            "digit commit",
            "band commit",
        ):
            decision = classify(prompt)
            self.assertNotIn("commit", decision["signals"], prompt)
            self.assertEqual(decision["agent"], "main", prompt)
            self.assertNotEqual(decision["rule"], "confirm", prompt)

    def test_loose_review_and_fix_runs_the_fix_first(self):
        decision = classify("review & fix ok thì make PR")
        self.assertEqual(
            decision["stages"],
            [
                {"stage": "implement", "agent": "main"},
                {"stage": "review", "agent": "main"},
                {"stage": "pr", "agent": "tier-haiku-release"},
            ],
        )

    def test_an_explicit_commit_before_a_pr_is_one_release_stage(self):
        decision = classify("git commit rồi make PR")
        self.assertEqual(decision["signals"], ["commit", "pr"])
        self.assertEqual(
            decision["stages"],
            [{"stage": "pr", "agent": "tier-haiku-release"}],
        )

    def test_review_then_fix_keeps_prompt_order(self):
        decision = classify("review rồi sửa bug")
        self.assertEqual(
            decision["stages"],
            [
                {"stage": "review", "agent": "main"},
                {"stage": "implement", "agent": "main"},
            ],
        )

    def test_metric_tag_is_not_an_image_bump(self):
        decision = classify("change the tag on the metric")
        self.assertNotIn("bump", decision["signals"])
        self.assertEqual(decision["agent"], "main")

    def test_improve_and_implement_stay_on_main_opus(self):
        for prompt in ("improve the retry handler", "implement pagination"):
            decision = classify(prompt)
            self.assertEqual(decision["agent"], "main", prompt)
            self.assertEqual(decision["model"], "opus", prompt)
            self.assertEqual(decision["rule"], "implement", prompt)
            self.assertIsNone(hook_payload(prompt))

    def test_review_code_stays_on_main_opus(self):
        decision = classify("review code của service payment")
        self.assertEqual(decision["agent"], "main")
        self.assertEqual(decision["model"], "opus")
        self.assertEqual(decision["rule"], "review")
        self.assertIsNone(hook_payload("review code của service payment"))

    def test_plan_for_a_feature_is_opus(self):
        decision = classify("plan cho tính năng refund")
        self.assertEqual(decision["agent"], "tier-plan")
        self.assertEqual(decision["rule"], "plan")

    def test_check_agent_log_is_haiku(self):
        decision = classify("check log của agent payment")
        self.assertEqual(decision["agent"], "tier-haiku")
        self.assertEqual(decision["rule"], "log-check")

    def test_log_check_hook_leaves_analysis_on_main(self):
        text = hook_payload("check log của service xxx để xem có bugs ko")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("`tier-haiku` fetches the log lines and returns those lines only", text)
        self.assertIn("decide whether to continue on the main Opus session", text)
        self.assertIn("Do not leave the conclusion to the subagent.", text)

    def test_log_then_fix_hook_leaves_analysis_on_main(self):
        text = hook_payload("check log rồi sửa bug trong handler")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("`tier-haiku` fetches the log lines and returns those lines only", text)
        self.assertIn("analyze them and decide whether to continue on the main Opus session", text)
        self.assertIn("If that analysis finds no error, stop there.", text)

    def test_haiku_agent_fetches_logs_without_a_verdict(self):
        text = (Path(__file__).resolve().parent / "agents" / "tier-haiku.md").read_text(encoding="utf-8")
        self.assertIn("Do not label them as an error", text)
        self.assertIn("If nothing can return those logs, stop", text)
        # The log fetch keeps the read tools, so logs that only Bash can reach
        # do not fall back onto the main session.
        self.assertIn("disallowedTools: Write, Edit, NotebookEdit, Agent\n", text)
        self.assertIn("`kubectl logs`", text)
        self.assertNotIn("có bằng chứng lỗi", text)
        self.assertNotIn("chưa thấy lỗi", text)
        self.assertNotIn("chưa đủ dữ liệu", text)

    def test_release_agent_owns_the_push_and_refuses_history_rewrites(self):
        release = (Path(__file__).resolve().parent / "agents" / "tier-haiku-release.md").read_text(encoding="utf-8")
        self.assertIn("Commit, push, and pull request. The delegation asks for the pull request.", release)
        self.assertIn("If a named path, the tag, or the file is missing, stop", release)
        self.assertIn("Only when the delegation says to merge", release)
        for forbidden in ("git add -A", "git commit --amend", "git reset", "git push --force"):
            self.assertIn(forbidden, release)
        self.assertIn("tools: Bash, Glob, Grep, Read, Edit\n", release)
        # This agent writes to the repo and opens pull requests, so project
        # instructions must reach it.
        self.assertNotIn("omitClaudeMd", release)

    def test_release_agent_stops_after_a_commit_only_stage(self):
        release = (Path(__file__).resolve().parent / "agents" / "tier-haiku-release.md").read_text(encoding="utf-8")
        self.assertIn("Pushing and opening a pull request are not implied by a commit", release)
        self.assertIn("Commit only.", release)
        self.assertIn("Do not push. Do not open a pull request.", release)
        self.assertIn("stop and ask the main {{Main}} session for them", release)
        # Commit, push, pull request, and an optional merge share one budget.
        self.assertIn("maxTurns: 25\n", release)
        self.assertIn("Report after each step that changed the repository or the remote", release)
        text = hook_payload("git commit the retry handler")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("commits the named paths and stops there: no push, and no pull request", text)
        self.assertIn("Say `commit only` in the delegation", text)

    def test_an_explicit_merge_mid_sentence_is_still_seen(self):
        for prompt in (
            "make a PR then merge it, sau đó bump image tag",
            "mở PR rồi gộp vào main",
            "make pr rồi merge nhé",
            "create a pr and merge",
            "make PR & merge to main",
            "make a pr then merge the PR",
        ):
            text = hook_payload(prompt)["hookSpecificOutput"]["additionalContext"]
            self.assertIn("The prompt asks to merge.", text, prompt)

    def test_a_conditional_clause_does_not_swallow_the_commit(self):
        for prompt in ("when tests pass, git commit", "when ci is green then git commit the fix"):
            self.assertIn("commit", classify(prompt)["signals"], prompt)

    def test_the_ambiguity_table_picks_one_commit_owner(self):
        text = hook_payload("lên kế hoạch sửa bug này")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Pick `commit` or `pr`, never both", text)

    def test_no_stage_flag_is_left_unread(self):
        source = (Path(__file__).resolve().parent / "route.py").read_text(encoding="utf-8")
        self.assertNotIn("hint_on_main", source)

    def test_agent_files_use_latest_aliases_and_fast_haiku_settings(self):
        root = Path(__file__).resolve().parent / "agents"
        expected = {
            "tier-haiku.md": "haiku",
            "tier-haiku-release.md": "haiku",
            "tier-plan.md": "fable",
            "Explore.md": "sonnet",
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

    def test_other_stays_on_main_opus(self):
        decision = classify("thêm pagination cho orders endpoint")
        self.assertEqual(decision["agent"], "main")
        self.assertEqual(decision["model"], "opus")
        self.assertEqual(decision["rule"], "default")
        self.assertIsNone(hook_payload("thêm pagination cho orders endpoint"))

    def test_fix_then_pr_is_split(self):
        decision = classify("fix bug rồi make PR")
        self.assertEqual(decision["rule"], "split")
        self.assertIsNone(decision["agent"])
        self.assertEqual(decision["signals"], ["implement", "pr"])
        self.assertEqual(
            [stage["stage"] for stage in decision["stages"]],
            ["implement", "pr"],
        )

    def test_review_pr_stays_on_main_opus(self):
        decision = classify("review the pull request")
        self.assertEqual(decision["agent"], "main")
        self.assertEqual(decision["model"], "opus")
        self.assertEqual(decision["rule"], "review")

    def test_log_then_fix_is_split(self):
        decision = classify("check log rồi sửa bug trong handler")
        self.assertEqual(decision["rule"], "split")
        self.assertIsNone(decision["agent"])
        self.assertEqual(decision["signals"], ["log", "implement"])

    def test_split_hook_lists_each_stage(self):
        text = hook_payload("lên plan rồi implement và make PR")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("- plan -> `tier-plan`", text)
        self.assertIn("- implement -> handle directly on the main Opus session", text)
        self.assertIn("- pr -> `tier-haiku-release` commits, pushes, and opens the pull request", text)
        self.assertIn("Start that stage only after review and the fix are OK", text)
        self.assertNotIn("- commit ->", text)

    def test_log_then_pr_hook_keeps_the_release_in_one_stage(self):
        text = hook_payload("check log rồi make PR")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("- log -> `tier-haiku`", text)
        self.assertIn("- pr -> `tier-haiku-release` commits, pushes, and opens the pull request", text)
        self.assertNotIn("- commit ->", text)

    def test_stages_follow_prompt_order(self):
        decision = classify("check log rồi lên plan")
        self.assertEqual(decision["rule"], "split")
        self.assertEqual(
            decision["stages"],
            [
                {"stage": "log", "agent": "tier-haiku"},
                {"stage": "plan", "agent": "tier-plan"},
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
                {"stage": "plan", "agent": "tier-plan"},
                {"stage": "pr", "agent": "tier-haiku-release"},
            ],
        )

    def test_fixing_log_code_or_image_tag_code_stays_on_main(self):
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
                {"stage": "pr", "agent": "tier-haiku-release"},
                {"stage": "bump", "agent": "tier-haiku-release"},
            ],
        )
        text = hook_payload(prompt)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Respect conditional gates", text)
        self.assertIn("directly on the main Opus session", text)
        self.assertIn("- pr -> `tier-haiku-release` commits, pushes, and opens the pull request", text)
        self.assertIn("Start that stage only after review and the fix are OK", text)
        self.assertIn("The prompt asks to merge.", text)
        log_at = text.index("- log ->")
        pr_at = text.index("- pr ->")
        bump_at = text.index("- bump ->")
        self.assertLess(log_at, pr_at)
        self.assertLess(pr_at, bump_at)

    def test_hook_stays_silent_on_slash_commands_mentions_and_pure_main_work(self):
        for prompt in ("/agents", "@tier-haiku fix this", "@agent-tier-plan check log", "Fix và review"):
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
            self.assertEqual(saved["model"], "opus")
            self.assertEqual(saved["effortLevel"], "high")
            self.assertEqual(saved["env"]["CLAUDE_CODE_SUBAGENT_MODEL"], "opus")
            orch = json.loads((root / "orchestrator.json").read_text(encoding="utf-8"))
            self.assertEqual(orch["mainModel"], "opus")
            self.assertEqual(orch["mainEffort"], "high")
            self.assertEqual(saved["attribution"]["commit"], "")
            install_hook(settings, script)
            again = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(len(again["hooks"]["UserPromptSubmit"]), 1)
            self.assertEqual(len(again["hooks"]["UserPromptSubmit"][0]["hooks"]), 1)

    def test_config_defaults_to_opus_high(self):
        cfg = load_config()
        self.assertEqual(cfg["mainModel"], "opus")
        self.assertEqual(cfg["mainEffort"], "high")
        # Not haiku: an agent file that pins no model of its own must not land
        # on Haiku without saying so.
        self.assertEqual(cfg["subagentModel"], "opus")

    def test_stage_models_match_the_agent_files(self):
        """route.py and the agent frontmatter must name the same model."""
        from route import _STAGES

        root = Path(__file__).resolve().parent / "agents"
        checked = 0
        for name, spec in _STAGES.items():
            if spec.agent == "main":
                continue
            front = (root / f"{spec.agent}.md").read_text(encoding="utf-8").split("---")[1]
            self.assertIn(f"\nmodel: {spec.model}\n", front, f"{name} -> {spec.agent}")
            checked += 1
        # plan, log, commit, pr, bump, release: the last four share
        # tier-haiku-release.
        self.assertEqual(checked, 6)

    def test_plan_runs_on_fable_at_high_effort(self):
        decision = classify("lên plan cho feature X")
        self.assertEqual(decision["agent"], "tier-plan")
        self.assertEqual(decision["model"], "fable")
        plan = (Path(__file__).resolve().parent / "agents" / "tier-plan.md").read_text(encoding="utf-8")
        self.assertIn("model: fable\n", plan)
        self.assertIn("effort: high\n", plan)

    def test_every_agent_pins_its_own_model(self):
        root = Path(__file__).resolve().parent / "agents"
        files = sorted(path.name for path in root.glob("*.md"))
        self.assertEqual(files, ["Explore.md", "tier-haiku-release.md", "tier-haiku.md", "tier-plan.md"])
        for name in files:
            front = (root / name).read_text(encoding="utf-8").split("---")[1]
            self.assertRegex(front, r"\nmodel: (?:haiku|sonnet|opus|fable)\n", name)

    def test_install_hook_can_pin_sonnet(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "settings.json"
            settings.write_text("{}\n", encoding="utf-8")
            install_hook(settings, root / "hook.py", main_model="sonnet")
            saved = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(saved["model"], "sonnet")
            self.assertEqual(saved["effortLevel"], "high")
            orch = json.loads((root / "orchestrator.json").read_text(encoding="utf-8"))
            self.assertEqual(orch["mainModel"], "sonnet")

    def test_install_hook_rejects_an_unknown_main_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = root / "settings.json"
            settings.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                install_hook(settings, root / "hook.py", main_model="haiku")

    def test_live_settings_can_select_sonnet(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "orchestrator.json"
            config.write_text(
                json.dumps({"mainModel": "opus", "mainEffort": "high", "subagentModel": "haiku"}),
                encoding="utf-8",
            )
            settings = root / "settings.json"
            settings.write_text(json.dumps({"model": "sonnet", "effortLevel": "low"}), encoding="utf-8")
            cfg = load_config_from(config, settings, settings_override=True)
            self.assertEqual(cfg["mainModel"], "sonnet")
            self.assertEqual(cfg["mainEffort"], "low")
            self.assertEqual(cfg["subagentModel"], "haiku")

    def test_skill_renders_for_opus_and_sonnet(self):
        raw = (Path(__file__).resolve().parent / "skill" / "SKILL.md").read_text(encoding="utf-8")
        opus = render_text(raw, "opus", "high")
        sonnet = render_text(raw, "sonnet", "high")
        self.assertIn("main Opus session", opus)
        self.assertIn('"model": "opus"', opus)
        self.assertIn("`tier-plan`", opus)
        self.assertNotIn("fix, review", opus)
        self.assertIn("fetches the logs and returns the lines only", opus)
        self.assertIn("commits the named paths, pushes, and opens the pull request", opus)
        self.assertIn("merge only when the prompt asks to merge", opus)
        self.assertIn("`tier-haiku-release`", opus)
        self.assertNotIn("{{", opus)
        self.assertIn("main Sonnet session", sonnet)
        self.assertIn("`tier-plan`", sonnet)
        self.assertNotIn("tier-sonnet", sonnet)
        self.assertNotIn("{{", sonnet)

    def test_agent_templates_render_the_main_model(self):
        root = Path(__file__).resolve().parent / "agents"
        for name in ("tier-plan.md", "tier-haiku.md", "tier-haiku-release.md", "Explore.md"):
            rendered = render_text((root / name).read_text(encoding="utf-8"), "opus", "high")
            self.assertNotIn("{{", rendered)
            self.assertIn("Opus", rendered)
        # A leftover "Sonnet" would mean an unrendered {{Main}} or a stale
        # tier-sonnet reference. Explore names Sonnet as its own pinned model.
        for name in ("tier-plan.md", "tier-haiku.md", "tier-haiku-release.md"):
            rendered = render_text((root / name).read_text(encoding="utf-8"), "opus", "high")
            self.assertNotIn("Sonnet", rendered, name)

    def test_explore_searches_on_sonnet_at_high_effort(self):
        explore = (Path(__file__).resolve().parent / "agents" / "Explore.md").read_text(encoding="utf-8")
        self.assertIn("model: sonnet\n", explore)
        self.assertIn("effort: high\n", explore)
        self.assertIn("tools: Glob, Grep, Read\n", explore)
        self.assertIn("Cite a line only after you have Read that file.", explore)
        self.assertIn("try a second wording before you report nothing", explore)
        self.assertIn("say the search is incomplete", explore)


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
