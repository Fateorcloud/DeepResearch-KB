"""Small SQLite knowledge store. No vector index or research routing yet."""

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from uuid import uuid4

from .models import DocumentVersion, Evidence, KnowledgeBase, SourceType

# Deliberately small English function-word list, not a domain vocabulary.
# Quoted phrases and uppercase acronyms bypass it (e.g. "The Who", IS).
_QUESTION_WORDS = frozenset("a an the is are was were be been being what which who where when why how do does did can could would should of for to in on at and or with about".split())


def _fts_query(query: str) -> str:
    terms = []
    for phrase, word in re.findall(r'"([^"]+)"|(\w+)', query):
        if phrase:
            words = re.findall(r"\w+", phrase)
            if words:
                terms.append('"' + " ".join(words) + '"')
        elif word.isupper() or word.casefold() not in _QUESTION_WORDS:
            terms.append('"' + word + '"')
    return " OR ".join(dict.fromkeys(terms))


def _chunks(pages):
    for page in pages:
        text = page["raw_content"].strip()
        for start in range(0, len(text), 1000):
            yield text[start:start + 1000]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _logical_path(value: str) -> str:
    value = value.replace("\\", "/")
    path = PurePosixPath(value)
    if not value.strip() or path.is_absolute() or ".." in path.parts or ":" in value:
        raise ValueError("logical_path must be a non-empty relative path without '..'")
    if str(path) == ".":
        raise ValueError("logical_path must identify a file")
    return str(path)


async def _load_upstream(path: Path) -> list[dict]:
    # Lazy import: metadata operations do not require GPTR's optional stack.
    from gpt_researcher.document import DocumentLoader

    # A string path is interpreted as a directory by upstream; use a file list.
    return await DocumentLoader([str(path)]).load()


class KnowledgeStore:
    """File-backed metadata and immutable content snapshots.

    Each operation owns its connection. Parsing happens before the short write
    transaction; failed parsing leaves the previous version unchanged.
    `loader` is an async callable accepting one staged Path, for offline tests.
    """

    def __init__(self, database: str | Path, *, loader=None):
        self.database = Path(database).resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.loader = loader or _load_upstream
        with closing(self._connect()) as db, db:
            if db.execute("PRAGMA user_version").fetchone()[0] > 1:
                raise ValueError("knowledge database schema is newer than this application")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS knowledge_base (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS document (
                    id TEXT PRIMARY KEY,
                    knowledge_base_id TEXT NOT NULL REFERENCES knowledge_base(id),
                    logical_path TEXT NOT NULL,
                    UNIQUE(knowledge_base_id, logical_path)
                );
                CREATE TABLE IF NOT EXISTS document_version (
                    document_id TEXT NOT NULL REFERENCES document(id),
                    version INTEGER NOT NULL,
                    source_type TEXT NOT NULL,
                    source_uri TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    ingested_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active', 'superseded')),
                    raw_bytes BLOB NOT NULL,
                    pages_json TEXT NOT NULL,
                    PRIMARY KEY(document_id, version)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_version
                    ON document_version(document_id) WHERE status = 'active';
                CREATE TABLE IF NOT EXISTS chunk (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    ordinal INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    UNIQUE(document_id, version, ordinal),
                    FOREIGN KEY(document_id, version) REFERENCES document_version(document_id, version)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
                    text, content='chunk', content_rowid='rowid'
                );
                CREATE TRIGGER IF NOT EXISTS chunk_ai AFTER INSERT ON chunk BEGIN
                    INSERT INTO chunk_fts(rowid, text) VALUES (new.rowid, new.text);
                END;
                CREATE TRIGGER IF NOT EXISTS chunk_ad AFTER DELETE ON chunk BEGIN
                    INSERT INTO chunk_fts(chunk_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
                END;
                CREATE TRIGGER IF NOT EXISTS chunk_au AFTER UPDATE ON chunk BEGIN
                    INSERT INTO chunk_fts(chunk_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
                    INSERT INTO chunk_fts(rowid, text) VALUES (new.rowid, new.text);
                END;
            """)
            # Historical Phase 1 databases had versions but no chunks, or chunks
            # created before the FTS triggers. Backfill and rebuild atomically.
            db.execute("BEGIN IMMEDIATE")
            if db.execute("PRAGMA user_version").fetchone()[0] == 0:
                rows = db.execute("""
                    SELECT v.document_id, v.version, v.pages_json FROM document_version v
                    WHERE NOT EXISTS (SELECT 1 FROM chunk c WHERE
                        c.document_id = v.document_id AND c.version = v.version)
                """).fetchall()
                for row in rows:
                    db.executemany("INSERT INTO chunk VALUES (?, ?, ?, ?, ?)", [
                        (uuid4().hex, row["document_id"], row["version"], ordinal, text)
                        for ordinal, text in enumerate(_chunks(json.loads(row["pages_json"])))
                    ])
                db.execute("INSERT INTO chunk_fts(chunk_fts) VALUES ('rebuild')")
                db.execute("PRAGMA user_version = 1")

    def _connect(self):
        db = sqlite3.connect(self.database)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def create_knowledge_base(self, name: str) -> KnowledgeBase:
        if not name.strip():
            raise ValueError("name must not be blank")
        kb = KnowledgeBase(uuid4().hex, name.strip(), _now())
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO knowledge_base VALUES (?, ?, ?)",
                       (kb.id, kb.name, kb.created_at))
        return kb

    def list_knowledge_bases(self) -> list[KnowledgeBase]:
        with closing(self._connect()) as db:
            return [KnowledgeBase(**dict(row)) for row in db.execute(
                "SELECT * FROM knowledge_base ORDER BY created_at, id")]

    @staticmethod
    def _version(row) -> DocumentVersion:
        data = dict(row)
        data["pages"] = tuple(json.loads(data.pop("pages_json")))
        return DocumentVersion(**data)

    def list_versions(self, knowledge_base_id: str, logical_path: str) -> list[DocumentVersion]:
        with closing(self._connect()) as db:
            rows = db.execute("""
                SELECT d.knowledge_base_id, d.logical_path, v.document_id,
                       v.version, v.source_type, v.source_uri, v.content_hash,
                       v.updated_at, v.ingested_at, v.status, v.pages_json
                FROM document d JOIN document_version v ON d.id = v.document_id
                WHERE d.knowledge_base_id = ? AND d.logical_path = ?
                ORDER BY v.version
            """, (knowledge_base_id, _logical_path(logical_path)))
            return [self._version(row) for row in rows]

    async def ingest(
        self, knowledge_base_id: str, file_path: str | Path, *,
        logical_path: str, source_type: SourceType = "local_import",
        source_uri: str | None = None, updated_at: datetime | None = None,
    ) -> DocumentVersion:
        """Import one file, including a file staged by a future Web Upload.

        Identity is (KB, logical_path), not a basename or temporary upload path.
        Repeating the current bytes returns the existing version and provenance.
        Changing bytes creates a new active version; old snapshots remain intact.
        No network downloads, embedding calls or automatic research occur here.
        """
        logical_path = _logical_path(logical_path)
        if source_type not in ("local_import", "web_upload"):
            raise ValueError("unsupported source_type")
        path = Path(file_path).resolve(strict=True)
        if not path.is_file():
            raise ValueError("file_path must be a file")
        if source_type == "web_upload" and not source_uri:
            raise ValueError("web_upload requires a stable source_uri, not a staging path")
        source_uri = path.as_uri() if source_uri is None else source_uri
        if not source_uri.strip():
            raise ValueError("source_uri must not be blank")
        if updated_at is None:
            updated_at = (datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                          if source_type == "local_import" else datetime.now(timezone.utc))
        if updated_at.tzinfo is None or updated_at.utcoffset() is None:
            raise ValueError("updated_at must be timezone-aware")
        with closing(self._connect()) as db:
            if not db.execute("SELECT 1 FROM knowledge_base WHERE id = ?",
                              (knowledge_base_id,)).fetchone():
                raise KeyError(f"Unknown knowledge base: {knowledge_base_id}")

        raw_bytes = path.read_bytes()
        digest = hashlib.sha256(raw_bytes).hexdigest()
        versions = self.list_versions(knowledge_base_id, logical_path)
        if versions and versions[-1].content_hash == digest:
            return versions[-1]

        # Parse exactly the bytes we hash/store, not a changing original file.
        # Preserve the logical extension even when an upload uses a random name.
        with TemporaryDirectory(prefix="deepresearch-kb-") as staging:
            staged = Path(staging) / PurePosixPath(logical_path).name
            staged.write_bytes(raw_bytes)
            pages = await self.loader(staged)
        if not isinstance(pages, list) or not pages or any(
            not isinstance(page, dict) or not isinstance(page.get("raw_content"), str)
            or not page["raw_content"].strip() for page in pages
        ):
            raise ValueError("loader must return non-empty text pages")
        pages_json = json.dumps(pages, ensure_ascii=False)

        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            doc = db.execute("SELECT id FROM document WHERE knowledge_base_id = ? AND logical_path = ?",
                             (knowledge_base_id, logical_path)).fetchone()
            document_id = doc["id"] if doc else uuid4().hex
            if not doc:
                db.execute("INSERT INTO document VALUES (?, ?, ?)",
                           (document_id, knowledge_base_id, logical_path))
            latest = db.execute("SELECT version, content_hash FROM document_version WHERE document_id = ? ORDER BY version DESC LIMIT 1",
                                (document_id,)).fetchone()
            # Recheck under the write lock for simultaneous imports.
            if not latest or latest["content_hash"] != digest:
                version = latest["version"] + 1 if latest else 1
                db.execute("UPDATE document_version SET status = 'superseded' WHERE document_id = ?",
                           (document_id,))
                db.execute("INSERT INTO document_version VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (document_id, version, source_type, source_uri, digest,
                            updated_at.astimezone(timezone.utc).isoformat(), _now(),
                            "active", raw_bytes, pages_json))
                # Deterministic lexical chunks are the Phase 1 retrieval seam.
                # A future vector adapter can replace this implementation while
                # retaining the document/version/chunk lineage.
                db.executemany("INSERT INTO chunk VALUES (?, ?, ?, ?, ?)", [
                    (uuid4().hex, document_id, version, ordinal, text)
                    for ordinal, text in enumerate(_chunks(pages)) if text
                ])
        return self.list_versions(knowledge_base_id, logical_path)[-1]

    def retrieve(self, knowledge_base_ids: list[str], query: str, *, limit: int = 5) -> list[Evidence]:
        """Return active-version evidence ranked by simple lexical overlap.

        This is intentionally deterministic and dependency-free. It is a
        baseline retrieval implementation, not a claim of semantic search.
        """
        if not knowledge_base_ids or not query.strip() or limit < 1:
            return []
        # FTS5 MATCH is a query language; natural-language punctuation such as
        # '?' must not be passed through as syntax. Quoting each token also
        # prevents operators in a user query from changing retrieval semantics.
        fts_query = _fts_query(query)
        if not fts_query:
            return []
        placeholders = ",".join("?" for _ in knowledge_base_ids)
        with closing(self._connect()) as db:
            rows = db.execute(f"""
                SELECT c.id, c.text, v.source_type, v.source_uri, d.logical_path,
                       d.id AS document_id, c.version, d.knowledge_base_id,
                       v.content_hash, v.updated_at, bm25(chunk_fts) AS rank
                FROM chunk c
                JOIN chunk_fts ON chunk_fts.rowid = c.rowid
                JOIN document d ON d.id = c.document_id
                JOIN document_version v ON v.document_id = c.document_id AND v.version = c.version
                WHERE d.knowledge_base_id IN ({placeholders}) AND v.status = 'active'
                  AND chunk_fts MATCH ?
            """, [*knowledge_base_ids, fts_query])
            scored = []
            for row in rows:
                scored.append((-float(row["rank"]), row))
        scored.sort(key=lambda item: (-item[0], item[1]["logical_path"], item[1]["version"], item[1]["id"]))
        return [Evidence(chunk_id=row["id"], text=row["text"], source_type=row["source_type"],
                         source_uri=row["source_uri"], logical_path=row["logical_path"],
                         document_id=row["document_id"], version=row["version"], score=float(score),
                         knowledge_base_id=row["knowledge_base_id"], content_hash=row["content_hash"],
                         updated_at=row["updated_at"])
                for score, row in scored[:limit]]

    def resolve_reference(self, reference: str) -> Evidence:
        """Resolve an immutable kb:// citation, including superseded versions."""
        match = re.fullmatch(r"kb://([^/]+)/versions/([1-9][0-9]*)/chunks/([^/]+)", reference)
        if not match:
            raise ValueError("invalid KB reference")
        document_id, version, chunk_id = match.groups()
        with closing(self._connect()) as db:
            row = db.execute("""
                SELECT c.id, c.text, c.document_id, c.version, d.knowledge_base_id,
                       d.logical_path, v.source_type, v.source_uri, v.content_hash, v.updated_at
                FROM chunk c JOIN document d ON d.id=c.document_id
                JOIN document_version v ON v.document_id=c.document_id AND v.version=c.version
                WHERE c.id=? AND c.document_id=? AND c.version=?
            """, (chunk_id, document_id, int(version))).fetchone()
        if row is None:
            raise KeyError("KB reference not found in this database")
        return Evidence(row["id"], row["text"], row["source_type"], row["source_uri"], row["logical_path"],
                        row["document_id"], row["version"], 0.0, row["knowledge_base_id"],
                        row["content_hash"], row["updated_at"])
