import unittest
from pathlib import Path

class Phase4ReportEffectsTests(unittest.TestCase):
    def test_effect_review_document_exists(self):
        self.assertTrue(Path("docs/deepresearch-kb/PHASE4_REPORT_EFFECTS.md").exists())
