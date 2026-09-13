import json
import os
import unittest
from pathlib import Path


class ConflictArtifactTests(unittest.TestCase):
    def test_real_conflict_artifact_has_five_valid_cases(self):
        path = Path("data/evals/phase3-conflicts-v1.json")
        if not path.exists():
            self.skipTest("real model artifact not present in a clean checkout")
        result = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(result["results"]), 5)
        self.assertTrue(all(row["passed"] and row["valid_review"] for row in result["results"]))
        self.assertEqual(result["usage"]["llm_tokens"], {"input_tokens": 1350, "output_tokens": 1708})
