import unittest
from pathlib import Path
from evals.deepresearch_kb.score_effect_reports import score

class ScoreEffectReportsTests(unittest.TestCase):
    def test_artifact_diagnostics_are_complete(self):
        if not Path("data/evals/effect-v2-reports-1/dataset.json").is_file():
            self.skipTest("live evaluation dataset not present in a clean checkout")
        result=score()
        self.assertEqual(len(result["results"]),24)
        self.assertTrue(all(not row["invalid_citations"] for row in result["results"]))
