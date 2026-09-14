import unittest
from unittest.mock import AsyncMock
from deepresearch_kb.adaptive import AdaptiveResearchRouter
from deepresearch_kb.models import Evidence
from deepresearch_kb.sufficiency import EvidenceRequirement
class AdaptiveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self): self.e=Evidence("e","fact","local_import","file:///x","x","d",1,1)
    async def test_kb_enough_stops(self):
        q,d=AsyncMock(),AsyncMock(); route,_,_=await AdaptiveResearchRouter(quick_search=q,deep_research=d).run("x",internal=[self.e]); self.assertEqual(route,"stop"); q.assert_not_awaited()
    async def test_kb_missing_uses_quick(self):
        q=AsyncMock(return_value=[self.e]); d=AsyncMock(); route,_,_=await AdaptiveResearchRouter(quick_search=q,deep_research=d).run("x",internal=[]); self.assertEqual(route,"quick"); d.assert_not_awaited()
    async def test_conflict_escalates_deep(self):
        q=AsyncMock(return_value=[]); d=AsyncMock(return_value=[self.e]); route,_,_=await AdaptiveResearchRouter(quick_search=q,deep_research=d).run("x",internal=[],conflict=True); self.assertEqual(route,"deep")

    async def test_requirements_and_judge_can_stop_after_quick(self):
        req=EvidenceRequirement("r", ("specific",)); judge=AsyncMock(); judge.judge.return_value={"status":"sufficient", "matched_claim_ids":["e:0"], "missing_claims":[]}
        q=AsyncMock(return_value=[self.e]); d=AsyncMock()
        route,_,decisions=await AdaptiveResearchRouter(quick_search=q,deep_research=d,requirements=[req],judge=judge).run("x",internal=[])
        self.assertEqual(route,"quick"); d.assert_not_awaited(); self.assertIn("semantic judge", decisions[-1].reason)

    async def test_deep_budget_zero_does_not_call_provider(self):
        d=AsyncMock()
        route,_,decisions=await AdaptiveResearchRouter(quick_search=AsyncMock(return_value=[]),deep_research=d,max_deep_calls=0).run("x",internal=[])
        self.assertEqual(route,"deep"); d.assert_not_awaited(); self.assertEqual(decisions[-1].terminal_status,"insufficient")

    async def test_deep_completion_is_not_automatically_sufficient(self):
        requirement = EvidenceRequirement("r", ("missing key fact",))
        router = AdaptiveResearchRouter(quick_search=AsyncMock(return_value=[]),
            deep_research=AsyncMock(return_value=[self.e]), requirements=[requirement])
        route, _, decisions = await router.run("x", internal=[])
        self.assertEqual(route, "deep")
        self.assertEqual(decisions[-1].terminal_status, "insufficient")

    async def test_deep_new_evidence_is_reassessed(self):
        router = AdaptiveResearchRouter(quick_search=AsyncMock(return_value=[]),
            deep_research=AsyncMock(return_value=[self.e]), requirements=[EvidenceRequirement("r", ("fact",))])
        _, _, decisions = await router.run("x", internal=[])
        self.assertEqual(decisions[-1].terminal_status, "sufficient")
