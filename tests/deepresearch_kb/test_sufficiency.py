import unittest
from dataclasses import replace
from deepresearch_kb.models import Evidence
from deepresearch_kb.sufficiency import EvidenceRequirement, SufficiencyJudge, assess_requirements, extract_claims
from unittest.mock import AsyncMock

class SufficiencyTests(unittest.TestCase):
    def setUp(self):
        self.internal=Evidence("i","SQLite is current.","local_import","file:///i","a","d",2,1,effective_at="2025",status="active")
        self.external=Evidence("e","WAL does not work on network filesystems.","external_web","https://e","e","",1,1)
    def test_claim_coverage_requires_all_declared_constraints(self):
        req=EvidenceRequirement("r",("SQLite is current.","WAL does not work"),("local_import","external_web"),2,True)
        result=assess_requirements([req],[self.internal,self.external])[0]
        self.assertTrue(result.satisfied); self.assertEqual(set(result.matched_evidence_ids),{"i","e"})
        self.assertEqual(len(extract_claims([self.internal,self.external])),2)

    async def test_semantic_judge_validates_shape_and_grounding(self):
        judge = SufficiencyJudge(AsyncMock(return_value='{"status":"sufficient","matched_claim_ids":["i:0"],"missing_claims":[],"reason":"quoted"}'))
        self.assertEqual((await judge.judge(EvidenceRequirement("r",("SQLite is current.",)), [self.internal]))["status"], "sufficient")
        bad = SufficiencyJudge(AsyncMock(return_value='{"status":"sufficient","matched_claim_ids":["nope"],"missing_claims":[],"reason":"x"}'))
        self.assertEqual((await bad.judge(EvidenceRequirement("r",("x",)), [self.internal]))["status"], "unknown")
    def test_missing_claim_and_stale_version_fail(self):
        req=EvidenceRequirement("r",("SQLite is current.","writer budget is one"),require_current_version=True)
        stale=replace(self.internal,status="superseded")
        result=assess_requirements([req],[stale])[0]
        self.assertFalse(result.satisfied); self.assertIn("writer budget is one", result.missing_claims)
