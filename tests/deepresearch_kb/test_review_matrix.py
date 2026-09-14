import json
import unittest
from pathlib import Path
from evals.deepresearch_kb.build_review_matrix import build


class ReviewMatrixTests(unittest.TestCase):
    def test_matrix_preserves_blank_review_labels(self):
        with __import__("tempfile").TemporaryDirectory() as directory:
            root = Path(directory)
            source = Path("data/evals/effect-v2-reports-1")
            target = root / "matrix.json"
            payload = build(source, target)
            self.assertEqual(len(payload["rows"]), 24)
            self.assertTrue(all(row["review"]["claim_status"] == "unreviewed" for row in payload["rows"]))
            self.assertEqual(len(json.loads(target.read_text())["rows"]), 24)
