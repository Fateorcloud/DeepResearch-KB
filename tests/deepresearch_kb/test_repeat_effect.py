import unittest
from evals.deepresearch_kb.repeat_effect_eval import main

class RepeatEffectTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_runs_are_stable(self):
        result=await main(3)
        self.assertTrue(result["stable"])
        self.assertEqual(result["summary"][0]["runs"],3)
