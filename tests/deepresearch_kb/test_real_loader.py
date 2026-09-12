"""Real upstream parser smoke tests; no LLM, embedding or search calls."""

import tempfile
import unittest
from pathlib import Path

from deepresearch_kb.knowledge import KnowledgeStore


class RealLoaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_txt_ingest_and_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "staged-upload"
            source.write_text("Internal architecture: SQLite stores metadata.", encoding="utf-8")
            store = KnowledgeStore(root / "kb.sqlite")
            kb = store.create_knowledge_base("Smoke")
            version = await store.ingest(kb.id, source, logical_path="design.txt",
                                         source_type="web_upload", source_uri="upload://smoke/1")
            self.assertIn("SQLite", version.pages[0]["raw_content"])
            self.assertEqual(version.pages[0]["url"], "design.txt")
            self.assertEqual(KnowledgeStore(store.database).list_versions(kb.id, "design.txt"), [version])

    async def test_real_unsupported_file_does_not_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "file.unsupported"
            source.write_text("not supported", encoding="utf-8")
            store = KnowledgeStore(root / "kb.sqlite")
            kb = store.create_knowledge_base("Smoke")
            with self.assertRaises(ValueError):
                await store.ingest(kb.id, source, logical_path=source.name)
            self.assertEqual(store.list_versions(kb.id, source.name), [])
