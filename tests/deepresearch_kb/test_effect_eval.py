import unittest
from evals.deepresearch_kb.run_effect_eval import evaluate
class EffectEvalTests(unittest.IsolatedAsyncioTestCase):
    async def test_controlled_routes(self):
        result=await evaluate(); self.assertEqual(result["passed"],result["total"])
