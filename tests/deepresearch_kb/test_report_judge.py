import unittest
from unittest.mock import AsyncMock
from pathlib import Path

class ReportJudgeArtifactTests(unittest.TestCase):
    def test_judge_artifact_is_optional_and_schema_checked(self):
        path=Path("data/evals/effect-v2-reports-1/judge.json")
        if not path.exists(): self.skipTest("live judge artifact not present")
        import json
        data=json.loads(path.read_text()); self.assertEqual(len(data["rows"]),24)
        self.assertTrue(all(r["verdict"] in ("correct","incorrect","unanswerable","unknown") for r in data["rows"]))
