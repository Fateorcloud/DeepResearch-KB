import unittest
from unittest.mock import AsyncMock
from deepresearch_kb.adaptive import AdaptiveResearchRouter
from deepresearch_kb.models import Evidence

class AdaptiveCheckerTests(unittest.IsolatedAsyncioTestCase):
    async def test_conflict_checker_forces_deep(self):
        e=Evidence("e","fact","local_import","file:///x","x","d",1,1)
        checker=AsyncMock(); checker.check.return_value={"conflict_detected":True}
        deep=AsyncMock(return_value=[e])
        route,_,_=await AdaptiveResearchRouter(quick_search=AsyncMock(return_value=[]),deep_research=deep).run_with_conflict_checker("x",internal=[e],conflict_checker=checker)
        self.assertEqual(route,"deep"); deep.assert_awaited_once()
