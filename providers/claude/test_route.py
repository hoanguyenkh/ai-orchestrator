#!/usr/bin/env python3
"""Lock the routing examples from the orchestrator policy."""

import unittest

from route import classify


class RouteTests(unittest.TestCase):
    def test_log_check_is_haiku(self):
        decision = classify("check log của service xxx để xem có bugs ko")
        self.assertEqual(decision["agent"], "tier-haiku")
        self.assertEqual(decision["rule"], "log-check")

    def test_log_check_without_accents(self):
        decision = classify("kiem tra log service payment co bug khong")
        self.assertEqual(decision["agent"], "tier-haiku")
        self.assertEqual(decision["rule"], "log-check")

    def test_fix_and_review_is_sonnet(self):
        decision = classify("Fix và review")
        self.assertEqual(decision["agent"], "tier-sonnet")
        self.assertEqual(decision["rule"], "fix-or-review")

    def test_plan_is_opus(self):
        decision = classify("Lên plan code")
        self.assertEqual(decision["agent"], "tier-opus")
        self.assertEqual(decision["rule"], "plan")

    def test_plan_that_mentions_a_fix_stays_opus(self):
        decision = classify("lên plan để fix bug service payment")
        self.assertEqual(decision["agent"], "tier-opus")
        self.assertEqual(decision["rule"], "plan")

    def test_make_pr_and_bump_tag_is_haiku(self):
        decision = classify("Make Pr & bump image tag")
        self.assertEqual(decision["agent"], "tier-haiku")
        self.assertEqual(decision["rule"], "pr-or-bump")

    def test_other_is_sonnet(self):
        decision = classify("thêm pagination cho orders endpoint")
        self.assertEqual(decision["agent"], "tier-sonnet")
        self.assertEqual(decision["rule"], "default")

    def test_fix_plus_pr_stays_sonnet(self):
        decision = classify("fix bug rồi make PR")
        self.assertEqual(decision["agent"], "tier-sonnet")
        self.assertEqual(decision["rule"], "fix-or-review")

    def test_review_pr_is_sonnet(self):
        decision = classify("review the pull request")
        self.assertEqual(decision["agent"], "tier-sonnet")
        self.assertEqual(decision["rule"], "fix-or-review")

    def test_log_check_plus_fix_is_sonnet(self):
        decision = classify("check log rồi sửa bug trong handler")
        self.assertEqual(decision["agent"], "tier-sonnet")
        self.assertEqual(decision["rule"], "fix-or-review")


if __name__ == "__main__":
    unittest.main()
