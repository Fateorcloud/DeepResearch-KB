import unittest
from evals.deepresearch_kb.run_plan_execution import evaluate


class PlanExecutionEvalTests(unittest.IsolatedAsyncioTestCase):
    async def test_policy_call_matrix(self):
        result = await evaluate()
        self.assertEqual(result["passed"], result["total"])
