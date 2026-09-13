import unittest
from deepresearch_kb.planning import RuleBasedSourcePlanner, plan_from_upstream_subqueries


class PlanningTests(unittest.TestCase):
    def test_explicit_policies(self):
        planner = RuleBasedSourcePlanner()
        self.assertEqual(planner.plan("x", ["What is our architecture?"]).questions[0].source_policy, "internal")
        self.assertEqual(planner.plan("x", ["What is the latest SQLite behavior?"]).questions[0].source_policy, "external")
        self.assertEqual(planner.plan("x", ["What is our current architecture and latest SQLite behavior?"]).questions[0].source_policy, "hybrid")

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError): RuleBasedSourcePlanner().plan(" ")
        with self.assertRaises(ValueError): RuleBasedSourcePlanner().plan("x", ["", " "])

    def test_upstream_subqueries_are_only_wrapped(self):
        plan = plan_from_upstream_subqueries("overall", ["What is our architecture?", "What is the latest SQLite behavior?"])
        self.assertEqual([item.source_policy for item in plan.questions], ["internal", "external"])
        self.assertEqual(plan.query, "overall")

    def test_generic_architecture_does_not_imply_internal_knowledge(self):
        question = RuleBasedSourcePlanner().plan("x", ["latest production architecture limitations"])
        self.assertEqual(question.questions[0].source_policy, "external")
