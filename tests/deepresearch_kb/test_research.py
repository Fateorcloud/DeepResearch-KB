import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from deepresearch_kb.models import Evidence
from deepresearch_kb.research import ResearchOrchestrator, UpstreamExternalResearch
class ResearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.internal = Evidence("c1", "internal architecture", "local_import", "file:///a", "a.md", "d1", 2, 1.0)
        self.store = SimpleNamespace(retrieve=lambda ids, query, limit: [self.internal])
    async def test_internal_mode_never_calls_external(self):
        external = SimpleNamespace(search=AsyncMock())
        self.assertEqual(await ResearchOrchestrator(self.store, external).research("architecture", mode="internal", knowledge_base_ids=["kb1"]), [self.internal])
        external.search.assert_not_awaited()
    async def test_hybrid_is_internal_first(self):
        external = SimpleNamespace(search=AsyncMock(return_value=[Evidence("e1", "external", "external_web", "https://x", "https://x", "", 1, 0.0)]))
        result = await ResearchOrchestrator(self.store, external).research("architecture", mode="hybrid", knowledge_base_ids=["kb1"])
        self.assertEqual([x.source_type for x in result], ["local_import", "external_web"])
    async def test_missing_external_adapter_is_explicit_error(self):
        with self.assertRaises(ValueError): await ResearchOrchestrator(self.store).research("x", mode="external")
    async def test_upstream_adapter_maps_web_records(self):
        researcher = SimpleNamespace(quick_search=AsyncMock(return_value=[{"body": "web fact", "href": "https://x"}, {"body": "missing"}]))
        result = await UpstreamExternalResearch(lambda query: researcher).search("fact")
        self.assertEqual(len(result), 1); self.assertEqual(result[0].source_type, "external_web")
