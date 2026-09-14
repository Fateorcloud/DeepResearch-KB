import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from evals.deepresearch_kb.run_effect_v2 import evaluate
from evals.deepresearch_kb.run_effect_reports_v2 import run


class ReportRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_arms_archived_and_unknown_usage_not_invented(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            routing = root / "routing.json"
            routing.write_text(json.dumps(await evaluate()), encoding="utf-8")
            def factory(query):
                return SimpleNamespace(cfg=SimpleNamespace(llm_kwargs={}, smart_llm_model="fake"),
                    write_report=AsyncMock(return_value="Fixture report"))
            result = await run(routing, root / "reports", factory=factory)
            self.assertEqual(len(result["results"]), 24)
            self.assertTrue(all(r["status"] == "completed" for r in result["results"]))
            self.assertTrue(all(r["llm_tokens"] is None for r in result["results"]))
            self.assertEqual(len(list((root / "reports").glob("*/*/report.md"))), 24)
            with self.assertRaises(FileExistsError):
                await run(routing, root / "reports", factory=factory)
