import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from deepresearch_kb.deep_adapter import UpstreamDeepResearch


class DeepAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_deep_mode_returns_sources_not_generated_context(self):
        researcher = SimpleNamespace(report_type="deep", conduct_research=AsyncMock(return_value="generated synthesis"),
            get_research_sources=Mock(return_value=[{"url":"https://example.test/docs", "raw_content":"Source fact"},
                                                   {"url":"https://empty.test"}, None]))
        result = await UpstreamDeepResearch(lambda q: researcher).search("query")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "Source fact")
        self.assertEqual(result[0].source_type, "external_web")
        researcher.conduct_research.assert_awaited_once()

    async def test_regular_research_cannot_be_mislabeled_deep(self):
        researcher = SimpleNamespace(report_type="research_report", conduct_research=AsyncMock())
        with self.assertRaises(ValueError):
            await UpstreamDeepResearch(lambda q: researcher).search("query")
        researcher.conduct_research.assert_not_awaited()
