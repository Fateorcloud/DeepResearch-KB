import json
import unittest
from pathlib import Path


class EffectDatasetTests(unittest.TestCase):
    def test_frozen_case_schema_and_splits(self):
        path = Path(__file__).resolve().parents[2] / "evals/deepresearch_kb/effect_cases_v2.json"
        cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
        self.assertEqual(len(cases), 12)
        self.assertEqual(len({c["id"] for c in cases}), 12)
        self.assertEqual(sum(c["split"] == "holdout" for c in cases), 6)
        for case in cases:
            self.assertTrue(case["question"] and case["required_claims"])
            self.assertIn(case["expected_route"], ("stop", "quick", "deep"))
            for stage in ("internal", "quick", "deep"):
                self.assertIsInstance(case[stage], list)
