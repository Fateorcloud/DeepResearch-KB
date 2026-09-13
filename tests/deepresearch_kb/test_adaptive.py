import unittest
from unittest.mock import AsyncMock
from deepresearch_kb.adaptive import AdaptiveResearchRouter
from deepresearch_kb.models import Evidence
class AdaptiveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self): self.e=Evidence("e","fact","local_import","file:///x","x","d",1,1)
    async def test_kb_enough_stops(self):
        q,d=AsyncMock(),AsyncMock(); route,_,_=await AdaptiveResearchRouter(quick_search=q,deep_research=d).run("x",internal=[self.e]); self.assertEqual(route,"stop"); q.assert_not_awaited()
    async def test_kb_missing_uses_quick(self):
        q=AsyncMock(return_value=[self.e]); d=AsyncMock(); route,_,_=await AdaptiveResearchRouter(quick_search=q,deep_research=d).run("x",internal=[]); self.assertEqual(route,"quick"); d.assert_not_awaited()
    async def test_conflict_escalates_deep(self):
        q=AsyncMock(return_value=[]); d=AsyncMock(return_value=[self.e]); route,_,_=await AdaptiveResearchRouter(quick_search=q,deep_research=d).run("x",internal=[],conflict=True); self.assertEqual(route,"deep")
