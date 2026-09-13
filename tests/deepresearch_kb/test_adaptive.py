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
        req=EvidenceRequirement("r", ("specific",)); judge=AsyncMock(); judge.judge.return_value={"status":"sufficient"}
        q=AsyncMock(return_value=[self.e]); d=AsyncMock()
        route,_,decisions=await AdaptiveResearchRouter(quick_search=q,deep_research=d,requirements=[req],judge=judge).run("x",internal=[])
        self.assertEqual(route,"quick"); d.assert_not_awaited(); self.assertIn("semantic judge", decisions[-1].reason)
