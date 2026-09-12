import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from deepresearch_kb.models import Evidence
from deepresearch_kb.research import ResearchOrchestrator
from deepresearch_kb.run_research import run


class RunTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_evidence_never_constructs_reporter(self):
        factory = Mock(side_effect=AssertionError("must not call"))
        store = SimpleNamespace(retrieve=Mock(return_value=[]))
        report, evidence = await ResearchOrchestrator(store).write_report(
            "question", mode="internal", knowledge_base_ids=["kb"], researcher_factory=factory)
        self.assertEqual(evidence, [])
        self.assertIn("skipped", report)
        factory.assert_not_called()

    async def test_hybrid_artifacts_and_metrics(self):
        evidence = Evidence("c", "internal", "local_import", "file:///a", "a", "d", 1, 1.0)
        store = SimpleNamespace(retrieve=Mock(return_value=[evidence]))
        def factory(query):
            return SimpleNamespace(quick_search=AsyncMock(return_value=[{"body": "external", "href": "https://example.test"}]),
                                   write_report=AsyncMock(return_value="report"), get_costs=lambda: 0.1)
        with tempfile.TemporaryDirectory() as directory:
            output = await run(store, "query", mode="hybrid", kb_ids=["kb"], output_dir=directory,
                               researcher_factory=factory)
            sources = json.loads((output / "sources.json").read_text())
            self.assertEqual(len(sources), 2)
            manifest = json.loads((output / "run.json").read_text())
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(manifest["upstream_reported_cost_usd"], 0.2)
            self.assertIsNone(manifest["llm_tokens"])
            self.assertIsNone(manifest["actual_cost_usd"])
            self.assertEqual(manifest["search_calls"], 1)
            self.assertEqual(manifest["deep_research_calls"], 0)

    async def test_failure_record_does_not_leak_exception_message(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                await run(None, "query", mode="external", kb_ids=[], output_dir=directory,
                          researcher_factory=Mock(side_effect=RuntimeError("secret-token")))
            content = next(Path(directory).glob("*/run.json")).read_text()
            self.assertNotIn("secret-token", content)
            self.assertEqual(json.loads(content)["status"], "failed")

    async def test_internal_path_and_failure_preserve_sources(self):
        evidence = Evidence("c", "internal", "local_import", "file:///a", "a", "d", 1, 1.0)
        store = SimpleNamespace(retrieve=Mock(return_value=[evidence]))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                await run(store, "query", mode="internal", kb_ids=["kb"], output_dir=directory,
                          researcher_factory=lambda q: SimpleNamespace(
                              write_report=AsyncMock(side_effect=RuntimeError("failed"))))
            folder = next(Path(directory).iterdir())
            self.assertEqual(len(json.loads((folder / "sources.json").read_text())), 1)
            record = json.loads((folder / "run.json").read_text())
            self.assertNotIn("quick_search", record["research_path"])
            self.assertEqual(record["search_calls"], 0)
