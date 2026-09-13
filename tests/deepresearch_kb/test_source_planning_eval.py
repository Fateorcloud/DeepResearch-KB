import unittest
from evals.deepresearch_kb.run_source_planning import evaluate


class SourcePlanningEvalTests(unittest.TestCase):
    def test_fixed_gold_is_fully_reproduced(self):
        result = evaluate()
        self.assertEqual(result["passed"], result["total"])
