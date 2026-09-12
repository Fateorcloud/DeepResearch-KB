"""Offline persistence/ingest contracts; no GPTR or provider installation needed."""

import hashlib
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from deepresearch_kb.knowledge import KnowledgeStore, _load_upstream


class KnowledgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.file = self.root / "random-upload-name"
        self.file.write_bytes(b"architecture v1")
        self.seen = []

        async def loader(path):
            self.seen.append(path)
            return [{"raw_content": path.read_text(), "url": path.name,
                     "extra": {"preserved": True}}]

        self.loader = loader
        self.store = KnowledgeStore(self.root / "knowledge.sqlite", loader=loader)
        self.kb = self.store.create_knowledge_base("Research")

    async def ingest(self, **kwargs):
        return await self.store.ingest(self.kb.id, self.file,
                                       logical_path="architecture/current.txt", **kwargs)

    async def test_provenance_survives_restart_and_input_deletion(self):
        result = await self.ingest()
        self.assertEqual(result.content_hash, hashlib.sha256(self.file.read_bytes()).hexdigest())
        self.assertEqual(result.source_uri, self.file.as_uri())
        self.assertEqual(result.source_type, "local_import")
        self.assertEqual(result.logical_path, "architecture/current.txt")
        self.assertEqual(result.pages[0]["extra"], {"preserved": True})
        self.file.unlink()
        reopened = KnowledgeStore(self.store.database, loader=self.loader)
        self.assertEqual(reopened.list_knowledge_bases(), [self.kb])
        self.assertEqual(reopened.list_versions(self.kb.id, result.logical_path), [result])
        self.assertFalse(self.seen[0].exists())

    async def test_duplicate_is_noop_and_updates_keep_history(self):
        first = await self.ingest()
        self.assertEqual(await self.ingest(), first)
        self.assertEqual(len(self.seen), 1)
        self.file.write_bytes(b"architecture v2")
        second = await self.ingest()
        self.assertEqual(second.document_id, first.document_id)
        self.assertEqual(second.version, 2)
        versions = self.store.list_versions(self.kb.id, first.logical_path)
        self.assertEqual([v.status for v in versions], ["superseded", "active"])
        self.assertEqual(versions[0].pages[0]["raw_content"], "architecture v1")
        # Reverting bytes creates a new revision rather than silently activating v1.
        self.file.write_bytes(b"architecture v1")
        self.assertEqual((await self.ingest()).version, 3)

    async def test_upload_uses_same_identity_and_logical_extension(self):
        first = await self.ingest()
        self.file.write_bytes(b"uploaded revision")
        uploaded = await self.ingest(source_type="web_upload", source_uri="upload://test/upload-2")
        self.assertEqual(first.document_id, uploaded.document_id)
        self.assertEqual(uploaded.source_type, "web_upload")
        self.assertEqual(uploaded.source_uri, "upload://test/upload-2")
        self.assertEqual(self.seen[-1].name, "current.txt")

    async def test_identity_is_scoped_by_kb_and_full_logical_path(self):
        first = await self.ingest()
        other_path = await self.store.ingest(self.kb.id, self.file, logical_path="other/current.txt")
        other_kb = self.store.create_knowledge_base("Other")
        other = await self.store.ingest(other_kb.id, self.file, logical_path=first.logical_path)
        self.assertEqual(len({first.document_id, other.document_id, other_path.document_id}), 3)

    async def test_parse_failure_is_atomic_and_staging_is_cleaned(self):
        first = await self.ingest()
        self.file.write_bytes(b"changed")

        async def failing(path):
            self.seen.append(path)
            raise RuntimeError("parser failed")

        self.store.loader = failing
        with self.assertRaises(RuntimeError):
            await self.ingest()
        self.assertEqual(self.store.list_versions(self.kb.id, first.logical_path), [first])
        self.assertFalse(self.seen[-1].exists())

    async def test_empty_parse_does_not_register_document(self):
        self.store.loader = AsyncMock(return_value=[])
        with self.assertRaises(ValueError):
            await self.ingest()
        self.assertEqual(self.store.list_versions(self.kb.id, "architecture/current.txt"), [])

    async def test_invalid_metadata_rejected(self):
        for logical_path in ("", ".", "../secret.txt", "/tmp/doc.txt", "C:\\doc.txt"):
            with self.subTest(path=logical_path), self.assertRaises(ValueError):
                await self.store.ingest(self.kb.id, self.file, logical_path=logical_path)
        for kwargs in ({"source_type": "web_upload"}, {"source_type": "unknown"},
                       {"source_uri": " "}, {"updated_at": datetime(2026, 1, 1)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                await self.ingest(**kwargs)
        with self.assertRaises(KeyError):
            await self.store.ingest("missing", self.file, logical_path="doc.txt")
        self.assertEqual(self.seen, [])

    async def test_upstream_adapter_passes_one_file_list(self):
        module = types.ModuleType("gpt_researcher.document")
        calls = []

        class DocumentLoader:
            def __init__(self, paths):
                calls.append(paths)

            async def load(self):
                return [{"raw_content": "parsed", "url": "document.txt"}]

        module.DocumentLoader = DocumentLoader
        with patch.dict(sys.modules, {"gpt_researcher.document": module}):
            result = await _load_upstream(self.file)
        self.assertEqual(calls, [[str(self.file)]])
        self.assertEqual(result[0]["raw_content"], "parsed")


if __name__ == "__main__":
    unittest.main()
