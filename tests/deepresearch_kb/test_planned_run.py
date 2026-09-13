import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from deepresearch_kb.models import Evidence
from deepresearch_kb.planned_run import run_planned


class PlannedRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_upstream_plan_is_preserved_and_report_artifacts_written(self):
        internal = Evidence("i", "architecture", "local_import", "file:///a", "a", "d", 1, 1.0)
        external = Evidence("e", "latest", "external_web", "https://e", "https://e", "", 1, 1.0)
        store = SimpleNamespace(retrieve=lambda ids, query, limit: [internal])
        adapter = SimpleNamespace(search=AsyncMock(return_value=[external]))
        reporter = SimpleNamespace(
            research_conductor=SimpleNamespace(plan_research=AsyncMock(return_value=["What is our architecture?", "What is the latest version?"])),
            external_adapter=adapter,
            write_report=AsyncMock(return_value="report"),
        )
        with tempfile.TemporaryDirectory() as directory:
            report, planned = await run_planned("overall", store=store, researcher=reporter,
                                                knowledge_base_ids=["kb"], output_dir=Path(directory) / "run")
            self.assertEqual(report, "report")
            self.assertEqual([item.source_policy for item in planned], ["internal", "external"])
            self.assertIn("latest", (Path(directory) / "run" / "evidence.json").read_text())
            reporter.write_report.assert_awaited_once()
