import json
import unittest
from pathlib import Path

class JudgeV2ArtifactTests(unittest.TestCase):
    def test_balanced_strict_judge_results(self):
        path=Path("data/evals/effect-v2-reports-1/judge-v2.json")
        if not path.exists(): self.skipTest("live judge artifact not present")
        data=json.loads(path.read_text()); self.assertEqual(len(data["rows"]),24)
        for arm in ("fixed_hybrid","adaptive"):
            rows=[r for r in data["rows"] if r["arm"]==arm]
            self.assertEqual(sum(r["verdict"] in ("correct","unanswerable") for r in rows),11)
            self.assertEqual(sum(r["verdict"]=="incorrect" for r in rows),1)
            self.assertEqual(sum(r["verdict"]=="unknown" for r in rows),0)
        self.assertEqual(data["usage"]["llm_tokens"], {"input_tokens":12941,"output_tokens":62446})
