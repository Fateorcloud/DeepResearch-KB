"""Persist explicit version governance separately from immutable source snapshots."""

from contextlib import closing
from datetime import datetime, timezone

from .version_policy import VersionCandidate, select_versions, utc
from .models import Evidence


class GovernedKnowledge:
    """Bind one time policy for all subquestions in a research task."""

    def __init__(self, store, *, as_of=None, include_superseded=False, include_deprecated=False):
        self.governance = VersionGovernance(store)
        self.as_of = utc(as_of if as_of is not None else datetime.now(timezone.utc))
        self.include_superseded = include_superseded
        self.include_deprecated = include_deprecated

    def retrieve(self, kb_ids, query, *, limit=5):
        return self.governance.retrieve(kb_ids, query, limit=limit, as_of=self.as_of,
            include_superseded=self.include_superseded, include_deprecated=self.include_deprecated)


class VersionGovernance:
    """Metadata facade over KnowledgeStore; no file content or chunk IDs change.

    Legacy versions inherit ingestion time, explicitly labelled inferred. An
    operator may correct effective dates without reparsing or re-embedding.
    """

    def __init__(self, store):
        self.store = store
        with closing(store._connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS version_governance (
                document_id TEXT NOT NULL, version INTEGER NOT NULL,
                effective_at TEXT NOT NULL, deprecated_at TEXT,
                authority INTEGER NOT NULL CHECK(authority BETWEEN 0 AND 100),
                effective_at_inferred INTEGER NOT NULL,
                PRIMARY KEY(document_id, version),
                FOREIGN KEY(document_id, version) REFERENCES document_version(document_id, version)
            )""")
        self.sync()

    def sync(self):
        """Idempotently import metadata for versions created by existing ingest."""
        with closing(self.store._connect()) as db, db:
            db.execute("""INSERT OR IGNORE INTO version_governance
                SELECT document_id, version, ingested_at, NULL, 0, 1 FROM document_version""")

    def metadata(self, document_id, version):
        """Return persisted governance metadata, including its inference marker."""
        self.sync()
        with closing(self.store._connect()) as db:
            row = db.execute("SELECT * FROM version_governance WHERE document_id=? AND version=?",
                             (document_id, version)).fetchone()
        if row is None:
            raise KeyError("unknown document version")
        return dict(row)

    def set_metadata(self, document_id, version, *, effective_at, authority=0, deprecated_at=None):
        candidate = VersionCandidate(document_id, version, effective_at, deprecated_at, authority)
        self.sync()
        with closing(self.store._connect()) as db, db:
            cursor = db.execute("""UPDATE version_governance SET effective_at=?, deprecated_at=?,
                authority=?, effective_at_inferred=0 WHERE document_id=? AND version=?""",
                (candidate.effective_at.isoformat(),
                 candidate.deprecated_at.isoformat() if candidate.deprecated_at else None,
                 authority, document_id, version))
            if cursor.rowcount != 1:
                raise KeyError("unknown document version")

    def select(self, kb_ids, *, as_of=None, include_superseded=False, include_deprecated=False):
        self.sync()
        if not kb_ids:
            return []
        at = utc(as_of if as_of is not None else datetime.now(timezone.utc))
        placeholders = ",".join("?" for _ in kb_ids)
        with closing(self.store._connect()) as db:
            rows = db.execute(f"""SELECT g.* FROM version_governance g
                JOIN document d ON d.id=g.document_id
                WHERE d.knowledge_base_id IN ({placeholders})""", kb_ids).fetchall()
        candidates = [VersionCandidate(r["document_id"], r["version"],
                      datetime.fromisoformat(r["effective_at"]),
                      datetime.fromisoformat(r["deprecated_at"]) if r["deprecated_at"] else None,
                      r["authority"]) for r in rows]
        return select_versions(candidates, at=at, include_superseded=include_superseded,
                               include_deprecated=include_deprecated)

    def retrieve(self, kb_ids, query, *, limit=5, as_of=None,
                 include_superseded=False, include_deprecated=False):
        """Select temporal versions independently of query, then rank matching chunks."""
        from .knowledge import _fts_query
        expression = _fts_query(query)
        if not expression or limit < 1 or not kb_ids:
            return []
        selected = {(s.candidate.document_id, s.candidate.version): s for s in self.select(
            kb_ids, as_of=as_of, include_superseded=include_superseded,
            include_deprecated=include_deprecated)}
        if not selected:
            return []
        placeholders = ",".join("?" for _ in kb_ids)
        with closing(self.store._connect()) as db:
            rows = db.execute(f"""SELECT c.*, d.knowledge_base_id, d.logical_path,
                v.source_type, v.source_uri, v.content_hash, v.updated_at,
                g.effective_at_inferred, bm25(chunk_fts) AS rank
                FROM chunk c JOIN chunk_fts ON chunk_fts.rowid=c.rowid
                JOIN document d ON d.id=c.document_id
                JOIN document_version v ON v.document_id=c.document_id AND v.version=c.version
                JOIN version_governance g ON g.document_id=c.document_id AND g.version=c.version
                WHERE d.knowledge_base_id IN ({placeholders}) AND chunk_fts MATCH ?
            """, [*kb_ids, expression]).fetchall()
        hits = []
        for row in rows:
            selection = selected.get((row["document_id"], row["version"]))
            if selection is None:
                continue
            candidate = selection.candidate
            hits.append(Evidence(row["id"], row["text"], row["source_type"], row["source_uri"],
                row["logical_path"], row["document_id"], row["version"], -float(row["rank"]),
                row["knowledge_base_id"], row["content_hash"], row["updated_at"],
                candidate.effective_at.isoformat(), selection.status, candidate.authority,
                selection.reason, bool(row["effective_at_inferred"])))
        # Authority is explicit metadata, applied only to time-eligible matches.
        hits.sort(key=lambda e: (-e.authority, -e.score, e.logical_path, e.version, e.chunk_id))
        return hits[:limit]
