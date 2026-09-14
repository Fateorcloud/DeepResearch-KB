import unittest
from pathlib import Path

class StaleRerunArtifactTests(unittest.TestCase):
    def test_adaptive_stale_rerun_contains_current_deep_fact(self):
        path=Path("data/evals/stale-rerun-v1/adaptive/report.md")
        if not path.exists(): self.skipTest("live artifact not present")
        text=path.read_text(); self.assertIn("PostgreSQL", text); self.assertIn("current metadata engine", text)
