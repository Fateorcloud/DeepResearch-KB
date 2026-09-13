import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from deepresearch_kb.governance import VersionGovernance
from deepresearch_kb.knowledge import KnowledgeStore


class GovernanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_authority_ranks_only_eligible_matching_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            async def loader(path):
                return [{"raw_content": path.read_text(), "url": path.name}]
            store = KnowledgeStore(root / "db", loader=loader)
            kb = store.create_knowledge_base("authority")
            source = root / "source.txt"
            governance = VersionGovernance(store)
            ids = {}
            for name, text, authority, year in [
                ("low", "SQLite SQLite SQLite", 10, 2024),
                ("high", "SQLite approved", 90, 2024),
                ("future", "SQLite", 100, 2028),
                ("unrelated", "PostgreSQL", 100, 2024),
            ]:
                source.write_text(text)
                version = await store.ingest(kb.id, source, logical_path=name + ".txt")
                ids[name] = version.document_id
                governance.set_metadata(version.document_id, 1,
                    effective_at=datetime(year,1,1,tzinfo=timezone.utc), authority=authority)
            hits = governance.retrieve([kb.id], "SQLite", limit=1,
                as_of=datetime(2026,1,1,tzinfo=timezone.utc))
            self.assertEqual(hits[0].document_id, ids["high"])
            self.assertEqual(hits[0].authority, 90)
            self.assertEqual(governance.metadata(ids["high"], 1)["effective_at_inferred"], 0)

    async def test_persistent_effective_dates_do_not_rewrite_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            async def loader(path):
                return [{"raw_content": path.read_text(), "url": path.name}]
            store = KnowledgeStore(root / "kb.sqlite", loader=loader)
            kb = store.create_knowledge_base("test")
            source = root / "a.txt"
            source.write_text("current SQLite")
            first = await store.ingest(kb.id, source, logical_path="a.txt")
            source.write_text("late historical PostgreSQL")
            second = await store.ingest(kb.id, source, logical_path="a.txt")
            governance = VersionGovernance(store)
            governance.set_metadata(first.document_id, 1, effective_at=datetime(2025,1,1,tzinfo=timezone.utc))
            governance.set_metadata(second.document_id, 2, effective_at=datetime(2024,1,1,tzinfo=timezone.utc), authority=100)
            reopened = VersionGovernance(KnowledgeStore(store.database))
            result = reopened.select([kb.id], as_of=datetime(2026,1,1,tzinfo=timezone.utc))
            self.assertEqual(result[0].candidate.version, 1)
            hits = reopened.retrieve([kb.id], "SQLite", as_of=datetime(2026,1,1,tzinfo=timezone.utc))
            self.assertEqual(hits[0].version, 1)
            self.assertEqual(hits[0].status, "active")
            self.assertFalse(hits[0].effective_at_inferred)
            self.assertEqual(reopened.retrieve([kb.id], "PostgreSQL", as_of=datetime(2026,1,1,tzinfo=timezone.utc)), [])
            historic = reopened.retrieve([kb.id], "PostgreSQL", as_of=datetime(2024,6,1,tzinfo=timezone.utc))
            self.assertEqual(historic[0].version, 2)
            from deepresearch_kb.run_research import run
            from types import SimpleNamespace
            from unittest.mock import AsyncMock
            import json
            reporter = SimpleNamespace(write_report=AsyncMock(return_value="historical report"))
            output = await run(store, "PostgreSQL", mode="internal", kb_ids=[kb.id],
                output_dir=root / "runs", governed=True,
                as_of=datetime(2024,6,1,tzinfo=timezone.utc), researcher_factory=lambda q: reporter)
            self.assertIn("Status: active", reporter.write_report.await_args.kwargs["ext_context"])
            self.assertEqual(json.loads((output / "sources.json").read_text())[0]["version"], 2)
            self.assertEqual(json.loads((output / "run.json").read_text())["version_policy"]["as_of"], "2024-06-01T00:00:00+00:00")
            from deepresearch_kb.research import render_evidence_context
            self.assertIn("Effective at:", render_evidence_context(historic))
            self.assertEqual(store.list_versions(kb.id, "a.txt")[0].content_hash, first.content_hash)
            self.assertEqual(reopened.select([], as_of=datetime(2026,1,1,tzinfo=timezone.utc)), [])
            with self.assertRaises(KeyError):
                governance.set_metadata("missing", 1, effective_at=datetime(2025,1,1,tzinfo=timezone.utc))
