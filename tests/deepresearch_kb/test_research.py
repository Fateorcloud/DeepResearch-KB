import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from deepresearch_kb.models import Evidence
from deepresearch_kb.research import ResearchOrchestrator, UpstreamExternalResearch, render_evidence_context
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

    def test_context_renderer_keeps_source_type_and_lineage(self):
        external = Evidence("e1", "release fact", "external_web", "https://example.test", "https://example.test", "", 1, 0.0)
        rendered = render_evidence_context([self.internal, external])
        self.assertIn("Internal Source", rendered)
        self.assertIn("External Source", rendered)
        self.assertIn("Version: 2", rendered)
        self.assertIn("https://example.test", rendered)

    async def test_report_adapter_delegates_rendered_context_upstream(self):
        researcher = SimpleNamespace(write_report=AsyncMock(return_value="report"))
        external = SimpleNamespace(search=AsyncMock(return_value=[]))
        report, evidence = await ResearchOrchestrator(self.store, external).write_report(
            "architecture", mode="internal", knowledge_base_ids=["kb1"],
            researcher_factory=lambda query: researcher)
        self.assertEqual(report, "report")
        self.assertEqual(len(evidence), 1)
        kwargs = researcher.write_report.await_args.kwargs
        self.assertIn("Internal Source", kwargs["ext_context"])
