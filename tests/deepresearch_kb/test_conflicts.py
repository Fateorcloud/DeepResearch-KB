import unittest
from dataclasses import replace

from deepresearch_kb.conflicts import inspect_version_overlap
from deepresearch_kb.conflicts import SemanticConflictChecker
from unittest.mock import AsyncMock
import json
from deepresearch_kb.models import Evidence


class ConflictWarningTests(unittest.TestCase):
    def test_multiple_versions_are_warned_not_adjudicated(self):
        one = Evidence("a", "SQLite", "local_import", "file:///a", "a", "d", 1, 1.0)
        two = replace(one, chunk_id="b", version=2, text="PostgreSQL")
        warnings = inspect_version_overlap([one, two])
        self.assertEqual(len(warnings), 1)
        self.assertEqual(len(warnings[0].references), 2)
        self.assertIn("not been evaluated", warnings[0].explanation)

    def test_chunks_of_same_version_and_external_urls_are_not_versions(self):
        one = Evidence("a", "SQLite", "local_import", "file:///a", "a", "d", 1, 1.0)
        self.assertEqual(inspect_version_overlap([one, replace(one, chunk_id="b")]), [])
        self.assertEqual(inspect_version_overlap([one, replace(one, source_type="external_web", version=2)]), [])


class SemanticConflictTests(unittest.IsolatedAsyncioTestCase):
    async def test_quotes_and_pair_coverage_validated(self):
        one = Evidence("a", "The approved budget is one writer.", "local_import", "file:///a", "a", "d", 1, 1.0)
        two = replace(one, chunk_id="b", document_id="e", text="The approved budget is eight writers.")
        payload = {"pairs": [{"left": 0, "right": 1, "verdict": "conflict",
            "left_quote": one.text, "right_quote": two.text,
            "reason": "Same budget and scope, incompatible writer counts; confirm effective times."}]}
        result = await SemanticConflictChecker(AsyncMock(return_value=json.dumps(payload))).check([one, two])
        self.assertTrue(result["conflict_detected"])
        self.assertEqual(len(result["pairs"][0]["references"]), 2)
        payload["pairs"][0]["left_quote"] = "hallucinated quotation"
        bad = await SemanticConflictChecker(AsyncMock(return_value=json.dumps(payload))).check([one, two])
        self.assertEqual(bad["status"], "unknown")
        empty = await SemanticConflictChecker(AsyncMock(return_value='{"pairs":[]}')).check([one, two])
        self.assertEqual(empty["status"], "unknown")
