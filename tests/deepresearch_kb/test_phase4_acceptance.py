import unittest
from pathlib import Path

class Phase4AcceptanceTests(unittest.TestCase):
    def test_acceptance_document_states_non_superiority(self):
        text=Path("docs/deepresearch-kb/PHASE4_ACCEPTANCE.md").read_text(encoding="utf-8")
        self.assertIn("报告质量在该小样本上持平", text)
        self.assertIn("尚无总成本下降证据", text)
