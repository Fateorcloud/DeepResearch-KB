import tempfile
import unittest
from pathlib import Path

from langchain_core.embeddings import Embeddings

from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.persistent_index import PersistentVectorIndex


class OfflineEmbeddings(Embeddings):
    """Deterministic test vectors, NOT a semantic model."""
    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        return [float("SQLite" in text), float("Postgres" in text), 0.1]


class PersistentIndexTests(unittest.IsolatedAsyncioTestCase):
    async def test_reload_idempotency_scope_and_stale_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            async def loader(path):
                return [{"raw_content": path.read_text(), "url": path.name}]

            store = KnowledgeStore(root / "kb.sqlite", loader=loader)
            selected = store.create_knowledge_base("Selected")
            other = store.create_knowledge_base("Other")
            file = root / "doc.txt"
            file.write_text("SQLite")
            await store.ingest(other.id, file, logical_path="doc.txt")
            file.write_text("Postgres")
            await store.ingest(selected.id, file, logical_path="doc.txt")
            path = root / "index.json"
            index = PersistentVectorIndex(path, OfflineEmbeddings(), embedding_id="test-v1:3")
            self.assertEqual(index.rebuild(store), 2)
            self.assertEqual(index.rebuild(store), 2)
            index = PersistentVectorIndex(path, OfflineEmbeddings(), embedding_id="test-v1:3")
            self.assertEqual(len(index.vector_store.store), 2)
            hits = index.search(store, "SQLite", knowledge_base_ids=[selected.id], limit=1)
            self.assertEqual(hits[0].text, "Postgres")  # scope filtering before top-k
            self.assertEqual(index.search(store, "SQLite", knowledge_base_ids=[]), [])
            file.write_text("SQLite updated")
            await store.ingest(selected.id, file, logical_path="doc.txt")
            self.assertEqual(index.search(store, "Postgres", knowledge_base_ids=[selected.id]), [])
            index.rebuild(store)
            self.assertEqual(index.search(store, "SQLite", knowledge_base_ids=[selected.id])[0].version, 2)
            with self.assertRaises(ValueError):
                PersistentVectorIndex(path, OfflineEmbeddings(), embedding_id="different")
            snapshot = path.read_bytes()

            class Failing(OfflineEmbeddings):
                def embed_documents(self, texts):
                    raise RuntimeError("embedding failed")

            index.embeddings = Failing()
            with self.assertRaises(RuntimeError):
                index.rebuild(store)
            self.assertEqual(path.read_bytes(), snapshot)
            self.assertFalse(list(root.glob("kb-index-*")))

    async def test_empty_rebuild_clears_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            store = KnowledgeStore(Path(directory) / "kb.sqlite")
            index = PersistentVectorIndex(Path(directory) / "index.json", OfflineEmbeddings(), embedding_id="test")
            self.assertEqual(index.rebuild(store, knowledge_base_ids=[]), 0)
            self.assertEqual(index.search(store, "x", knowledge_base_ids=["missing"]), [])
