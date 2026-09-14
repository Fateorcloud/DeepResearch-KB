import unittest
from dataclasses import replace
from unittest.mock import AsyncMock
from deepresearch_kb.models import Evidence
from deepresearch_kb.sufficiency import EvidenceRequirement, grounded_judge_sufficient
from deepresearch_kb.adaptive import AdaptiveResearchRouter


class GateTests(unittest.IsolatedAsyncioTestCase):
    def test_negated_text_does_not_support_positive_claim(self):
        from deepresearch_kb.sufficiency import _claim_supported
        self.assertFalse(_claim_supported("Aurora permits remote storage", "It is false that Aurora permits remote storage."))

    async def test_unknown_checker_is_not_silently_conflict_free(self):
        e = Evidence("i", "fact", "local_import", "file:///a", "a", "d", 1, 1)
        checker = AsyncMock()
        checker.check.return_value = {"status": "unknown", "pairs": []}
        quick, deep = AsyncMock(return_value=[]), AsyncMock(return_value=[])
        route, _, decisions = await AdaptiveResearchRouter(quick_search=quick, deep_research=deep).run_with_conflict_checker(
            "query", internal=[e], conflict_checker=checker)
        self.assertNotEqual(route, "stop")
        self.assertEqual(decisions[-1].terminal_status, "unknown")

    async def test_judge_cannot_override_missing_external_source(self):
        e = Evidence("i", "paraphrased fact", "local_import", "file:///a", "a", "d", 1, 1, status="active")
        req = EvidenceRequirement("r", ("required fact",), ("external_web",))
        judge = AsyncMock()
        judge.judge.return_value = {"status":"sufficient", "matched_claim_ids":["i:0"], "missing_claims":[]}
        deep = AsyncMock(return_value=[])
        route, _, _ = await AdaptiveResearchRouter(quick_search=AsyncMock(return_value=[]),
            deep_research=deep, requirements=[req], judge=judge).run("query", internal=[e])
        self.assertEqual(route, "deep")
        deep.assert_awaited_once()

    def test_stale_duplicate_and_empty_support_rejected(self):
        e = Evidence("i", "fact", "local_import", "file:///a", "a", "d", 1, 1, status="superseded")
        review = {"status":"sufficient", "matched_claim_ids":["i:0"], "missing_claims":[]}
        self.assertFalse(grounded_judge_sufficient(EvidenceRequirement("r",("fact",),require_current_version=True), [e], review))
        req = EvidenceRequirement("r",("fact",),minimum_distinct_sources=2)
        self.assertFalse(grounded_judge_sufficient(req,[e,replace(e,chunk_id="j")],review))
        self.assertFalse(grounded_judge_sufficient(req,[e],{**review,"matched_claim_ids":[]}))
