"""Small-corpus vector snapshots backed by LangChain, not a database server."""

import json
from dataclasses import replace
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from langchain_core.vectorstores import InMemoryVectorStore

from .models import Evidence
from .vector_index import chunk_documents


class PersistentVectorIndex:
    """Explicit full rebuild; atomic JSON publication; no implicit provider calls.

    Use a dedicated file. Rebuild replaces this index's entire contents. Embedding
    identity must describe provider/model/dimension; callers own its correctness.
    Searches filter against current SQLite chunks before top-k. Unindexed new
    versions remain missing until rebuild, never replaced by obsolete evidence.
    """

    def __init__(self, path, embeddings, *, embedding_id: str):
        if not embedding_id.strip():
            raise ValueError("embedding_id is required")
        self.path = Path(path)
        self.embeddings = embeddings
        self.embedding_id = embedding_id
        self.vector_store = InMemoryVectorStore(embeddings)
        if self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema") != 1 or payload.get("embedding_id") != embedding_id:
                raise ValueError("index schema or embedding identity mismatch")
            self.vector_store.store = payload["vectors"]

    def rebuild(self, knowledge_store, *, knowledge_base_ids=None, include_all_versions=False) -> int:
        documents = chunk_documents(knowledge_store, knowledge_base_ids, include_all_versions=include_all_versions)
        candidate = InMemoryVectorStore(self.embeddings)
        if documents:
            candidate.add_documents(documents, ids=[d.metadata["chunk_id"] for d in documents])
        payload = {"schema": 1, "embedding_id": self.embedding_id, "vectors": candidate.store}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                    prefix="kb-index-", delete=False) as file:
                temporary = Path(file.name)
                json.dump(payload, file, ensure_ascii=False, allow_nan=False)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.vector_store = candidate
        return len(documents)

    def search(self, knowledge_store, query, *, knowledge_base_ids, limit=5):
        if not query.strip() or not knowledge_base_ids or limit < 1:
            return []
        # SQLite remains authoritative for both active version and KB membership.
        active = {d.metadata["chunk_id"]: d for d in
                  chunk_documents(knowledge_store, knowledge_base_ids)}
        if not active:
            return []
        results = self.vector_store.similarity_search_with_score(
            query, k=limit, filter=lambda doc: doc.metadata["chunk_id"] in active,
        )
        evidence = []
        for indexed, score in results:
            doc = active[indexed.metadata["chunk_id"]]
            meta = doc.metadata
            evidence.append(Evidence(meta["chunk_id"], doc.page_content, meta["source_type"],
                                     meta["source_uri"], meta["logical_path"],
                                     meta["document_id"], meta["version"], score,
                                     knowledge_base_id=meta["knowledge_base_id"],
                                     content_hash=meta["content_hash"], updated_at=meta["updated_at"]))
        return evidence

    def search_governed(self, knowledge_store, query, *, knowledge_base_ids, limit=5,
                        as_of=None, include_superseded=False, include_deprecated=False):
        """Use the same time selection as FTS; fail on incomplete historical index."""
        from .governance import VersionGovernance
        if not query.strip() or not knowledge_base_ids or limit < 1:
            return []
        governance = VersionGovernance(knowledge_store)
        selected = {(s.candidate.document_id, s.candidate.version): s for s in governance.select(
            knowledge_base_ids, as_of=as_of, include_superseded=include_superseded,
            include_deprecated=include_deprecated)}
        eligible = {d.metadata["chunk_id"]: d for d in chunk_documents(
            knowledge_store, knowledge_base_ids, include_all_versions=True)
            if (d.metadata["document_id"], d.metadata["version"]) in selected}
        if not eligible:
            return []
        if set(eligible) - set(self.vector_store.store):
            raise ValueError("index misses selected versions; rebuild with include_all_versions=True")
        matches = self.vector_store.similarity_search_with_score(query, k=len(eligible),
            filter=lambda d: d.metadata["chunk_id"] in eligible)
        output = []
        for indexed, score in matches:
            meta = eligible[indexed.metadata["chunk_id"]].metadata
            selection = selected[(meta["document_id"], meta["version"])]
            reference = f"kb://{meta['document_id']}/versions/{meta['version']}/chunks/{meta['chunk_id']}"
            evidence = knowledge_store.resolve_reference(reference)
            governance_metadata = governance.metadata(meta["document_id"], meta["version"])
            output.append(replace(evidence, score=score, effective_at=selection.candidate.effective_at.isoformat(),
                status=selection.status, authority=selection.candidate.authority,
                version_selection_reason=selection.reason,
                effective_at_inferred=bool(governance_metadata["effective_at_inferred"])))
        output.sort(key=lambda e: (-e.authority, -e.score, e.logical_path, e.version, e.chunk_id))
        return output[:limit]
