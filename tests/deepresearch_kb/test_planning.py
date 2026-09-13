import unittest
from deepresearch_kb.planning import RuleBasedSourcePlanner


class PlanningTests(unittest.TestCase):
    def test_explicit_policies(self):
        planner = RuleBasedSourcePlanner()
        self.assertEqual(planner.plan("x", ["What is our architecture?"]).questions[0].source_policy, "internal")
        self.assertEqual(planner.plan("x", ["What is the latest SQLite behavior?"]).questions[0].source_policy, "external")
        self.assertEqual(planner.plan("x", ["What is our current architecture and latest SQLite behavior?"]).questions[0].source_policy, "hybrid")

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError): RuleBasedSourcePlanner().plan(" ")
        with self.assertRaises(ValueError): RuleBasedSourcePlanner().plan("x", ["", " "])
