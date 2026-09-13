import unittest
from evals.deepresearch_kb.run_version_governance import evaluate


class VersionEvalTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_expectations_and_baseline_gap(self):
        result = await evaluate()
        self.assertEqual(result["total"], 6)
        self.assertEqual(result["baseline_passed"], 2)
        self.assertEqual(result["governed_passed"], 6)
