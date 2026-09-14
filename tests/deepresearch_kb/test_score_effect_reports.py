import unittest
from pathlib import Path
from evals.deepresearch_kb.score_effect_reports import score

class ScoreEffectReportsTests(unittest.TestCase):
    def test_artifact_diagnostics_are_complete(self):
        result=score()
        self.assertEqual(len(result["results"]),24)
        self.assertTrue(all(not row["invalid_citations"] for row in result["results"]))
