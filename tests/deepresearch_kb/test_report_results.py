import hashlib
import json
import unittest
from pathlib import Path

from evals.deepresearch_kb.summarize_reports import summarize


class ReportArtifactTests(unittest.TestCase):
    def test_fixed_artifacts_have_review_and_real_usage(self):
        root = Path(__file__).resolve().parents[2] / "evals/deepresearch_kb"
        results = root / "results/phase1-v1"
        manifest = json.loads((results / "manifest.json").read_text())
        self.assertEqual(hashlib.sha256((root / "report_cases.json").read_bytes()).hexdigest(), manifest["dataset_sha256"])
        self.assertEqual(len(manifest["results"]), 9)
        summary = summarize(results)
        self.assertEqual(summary["kb_only"]["supported_facts"], 4)
        self.assertEqual(summary["project_hybrid"]["supported_facts"], 9)
        for record in manifest["results"]:
            folder = results / record["case_id"] / record["arm"]
            self.assertTrue((folder / "report.md").read_text().strip())
            self.assertTrue((folder / "context.txt").read_text().strip())
            self.assertEqual(record["status"], "completed")
            self.assertGreater(record["llm_tokens"]["input_tokens"], 0)
            self.assertEqual(record["unknown_citation_links"], [])
