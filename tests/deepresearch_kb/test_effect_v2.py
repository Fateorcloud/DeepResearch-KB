import unittest
from evals.deepresearch_kb.run_effect_v2 import evaluate


class EffectComparisonTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_arms_and_failures_remain_visible(self):
        result = await evaluate()
        self.assertEqual(len(result["results"]), 24)
        adaptive = [r for r in result["results"] if r["arm"] == "adaptive"]
        # Existing substring matching incorrectly accepts negation; preserve
        # this observation rather than changing the held-out expected fact.
        negation = next(r for r in adaptive if r["id"] == "holdout_negation")
        self.assertFalse(negation["sufficient_on_unanswerable"])
        for row in result["results"]:
            if row["arm"] == "fixed_hybrid":
                self.assertEqual(row["calls"], {"internal":1, "quick":1, "deep":0})
