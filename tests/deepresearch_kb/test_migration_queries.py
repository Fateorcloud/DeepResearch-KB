import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from deepresearch_kb.knowledge import KnowledgeStore, _fts_query
from deepresearch_kb.research import citation_uri


class MigrationQueryTests(unittest.IsolatedAsyncioTestCase):
    def test_function_words_and_exact_phrases(self):
        self.assertEqual(_fts_query("What is SQLite?"), '"SQLite"')
        self.assertEqual(_fts_query('"The Who" IS SQL OR'), '"The Who" OR "IS" OR "SQL" OR "OR"')
        self.assertEqual(_fts_query("what is the?"), "")
        self.assertEqual(_fts_query('SQLite - metadata?'), '"SQLite" OR "metadata"')

    def test_chinese_is_queried_as_character_bigrams(self):
        self.assertEqual(_fts_query("依赖注入？"), '"依赖" OR "赖注" OR "注入"')
        self.assertEqual(_fts_query("安装PyJWT库"), '"安装" OR "PyJWT" OR "库"')
        self.assertEqual(_fts_query('"依赖注入"'), '"依赖 赖注 注入"')

    async def test_legacy_versions_and_pretrigger_chunks_backfill_once(self):
        for had_chunks in (False, True):
            with self.subTest(had_chunks=had_chunks), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "db.sqlite"
                file = Path(directory) / "doc.txt"
                async def loader(p):
                    return [{"raw_content": p.read_text(), "url": p.name}]
                store = KnowledgeStore(path, loader=loader)
                kb = store.create_knowledge_base("Legacy")
                file.write_text("oldmarker")
                await store.ingest(kb.id, file, logical_path="a.txt")
                file.write_text("SQLite currentmarker")
                await store.ingest(kb.id, file, logical_path="a.txt")
                # Reproduce both historical schemas without touching user DBs.
                with sqlite3.connect(path) as db:
                    db.execute("DROP TRIGGER chunk_terms_ad")
                    db.execute("DROP TABLE chunk_terms")
                    if not had_chunks:
                        db.execute("DROP TABLE chunk")
                    db.execute("PRAGMA user_version=0")
                migrated = KnowledgeStore(path)
                hit = migrated.retrieve([kb.id], "What is SQLite?")[0]
                self.assertEqual(hit.version, 2)
                self.assertEqual(migrated.retrieve([kb.id], "oldmarker"), [])
                self.assertEqual(len(migrated.list_versions(kb.id, "a.txt")), 2)
                again = KnowledgeStore(path)
                self.assertEqual(again.retrieve([kb.id], "SQLite")[0].chunk_id, hit.chunk_id)
                reference = citation_uri(hit)
                file.write_text("replacementmarker")
                await KnowledgeStore(path, loader=loader).ingest(kb.id, file, logical_path="a.txt")
                self.assertEqual(again.resolve_reference(reference).text, "SQLite currentmarker")
                with self.assertRaises(ValueError):
                    again.resolve_reference("file:///etc/passwd")
                with sqlite3.connect(path) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM chunk").fetchone()[0], 3)
                    self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    async def test_schema_1_unicode61_index_is_rebuilt_as_bigrams(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "db.sqlite"
            file = Path(directory) / "doc.txt"
            async def loader(p):
                return [{"raw_content": p.read_text(encoding="utf-8"), "url": p.name}]
            store = KnowledgeStore(path, loader=loader)
            kb = store.create_knowledge_base("Legacy")
            file.write_text("在编程中，依赖注入指的是声明运行所需的东西。SQLite", encoding="utf-8")
            await store.ingest(kb.id, file, logical_path="di.txt")
            # Rebuild the schema-1 index: raw text, unicode61, sync triggers.
            with sqlite3.connect(path) as db:
                db.execute("DROP TRIGGER chunk_terms_ad")
                db.execute("DROP TABLE chunk_terms")
                db.executescript("""
                    CREATE VIRTUAL TABLE chunk_fts USING fts5(text, content='chunk', content_rowid='rowid');
                    CREATE TRIGGER chunk_ai AFTER INSERT ON chunk BEGIN
                        INSERT INTO chunk_fts(rowid, text) VALUES (new.rowid, new.text); END;
                    CREATE TRIGGER chunk_ad AFTER DELETE ON chunk BEGIN
                        INSERT INTO chunk_fts(chunk_fts, rowid, text) VALUES ('delete', old.rowid, old.text); END;
                    CREATE TRIGGER chunk_au AFTER UPDATE ON chunk BEGIN
                        INSERT INTO chunk_fts(chunk_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
                        INSERT INTO chunk_fts(rowid, text) VALUES (new.rowid, new.text); END;
                    INSERT INTO chunk_fts(chunk_fts) VALUES ('rebuild');
                    PRAGMA user_version = 1;
                """)
                legacy = db.execute("SELECT COUNT(*) FROM chunk_fts WHERE chunk_fts MATCH '\"依赖注入\"'").fetchone()[0]
            self.assertEqual(legacy, 0)
            migrated = KnowledgeStore(path, loader=loader)
            self.assertEqual(len(migrated.retrieve([kb.id], "什么是依赖注入？")), 1)
            self.assertEqual(len(migrated.retrieve([kb.id], "SQLite")), 1)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
                names = {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
            self.assertFalse(names & {"chunk_fts", "chunk_ai", "chunk_ad", "chunk_au"})

    async def test_migration_failure_rolls_back_and_can_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "db.sqlite"
            store = KnowledgeStore(path)
            kb = store.create_knowledge_base("Legacy")
            with sqlite3.connect(path) as db:
                db.execute("INSERT INTO document VALUES ('d', ?, 'doc.txt')", (kb.id,))
                db.execute("INSERT INTO document_version VALUES ('d',1,'local_import','file:///a','hash','now','now','active',?,?)",
                           (b"SQLite", "invalid json"))
                db.execute("PRAGMA user_version=0")
            with self.assertRaises(json.JSONDecodeError):
                KnowledgeStore(path)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM chunk").fetchone()[0], 0)
                db.execute("UPDATE document_version SET pages_json=?",
                           (json.dumps([{"raw_content": "SQLite"}]),))
            self.assertEqual(len(KnowledgeStore(path).retrieve([kb.id], "SQLite")), 1)
