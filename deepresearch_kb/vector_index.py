"""Optional LangChain vector-index Adapter for persisted KB chunks."""

from typing import Any
from contextlib import closing

from .models import Evidence


def chunk_documents(store, knowledge_base_ids: list[str] | None = None, *, include_all_versions=False):
    """Export active chunks as LangChain Documents with complete provenance."""
    from langchain_core.documents import Document

    ids = ([kb.id for kb in store.list_knowledge_bases()]
           if knowledge_base_ids is None else knowledge_base_ids)
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    version_filter = "" if include_all_versions else "AND v.status = 'active'"
    with closing(store._connect()) as db:
        rows = db.execute(f"""
            SELECT c.id, c.text, c.document_id, c.version, d.knowledge_base_id,
                   d.logical_path, v.source_type, v.source_uri, v.content_hash, v.updated_at
            FROM chunk c JOIN document d ON d.id = c.document_id
            JOIN document_version v ON v.document_id = c.document_id AND v.version = c.version
            WHERE d.knowledge_base_id IN ({placeholders}) {version_filter}
            ORDER BY d.logical_path, c.version, c.ordinal
        """, ids)
        return [Document(page_content=row["text"], metadata={
            "chunk_id": row["id"], "knowledge_base_id": row["knowledge_base_id"],
            "document_id": row["document_id"], "version": row["version"],
            "logical_path": row["logical_path"], "source_type": row["source_type"],
            "source_uri": row["source_uri"], "source": row["source_uri"],
            "content_hash": row["content_hash"], "updated_at": row["updated_at"],
        }) for row in rows]


class LangChainVectorIndexBuilder:
    """Index active KB chunks into an injected LangChain vector store."""

    def __init__(self, vector_store):
        if not hasattr(vector_store, "add_documents"):
            raise TypeError("vector_store must provide add_documents")
        self.vector_store = vector_store

    def index(self, store, *, knowledge_base_ids: list[str] | None = None) -> int:
        documents = chunk_documents(store, knowledge_base_ids)
        if documents:
            self.vector_store.add_documents(documents)
        return len(documents)


class LangChainVectorIndex:
    """Adapt a caller-owned LangChain vector store to the KB Evidence seam.

    The vector store remains an injected dependency. This module never creates
    credentials, connects to a provider, or changes upstream research code.
    """

    def __init__(self, vector_store: Any):
        if not hasattr(vector_store, "similarity_search"):
            raise TypeError("vector_store must provide similarity_search")
        self.vector_store = vector_store

    def search(self, query: str, *, limit: int = 5, knowledge_base_ids: list[str] | None = None) -> list[Evidence]:
        if not query.strip() or limit < 1:
            return []
        docs = self.vector_store.similarity_search(query, k=limit)
        results = []
        for index, doc in enumerate(docs):
            metadata = dict(getattr(doc, "metadata", {}) or {})
            kb_id = metadata.get("knowledge_base_id")
            if knowledge_base_ids and kb_id not in knowledge_base_ids:
                continue
            results.append(Evidence(
                chunk_id=str(metadata.get("chunk_id", index)),
                text=str(getattr(doc, "page_content", "")),
                source_type=metadata.get("source_type", "local_import"),
                source_uri=str(metadata.get("source_uri", metadata.get("source", ""))),
                logical_path=str(metadata.get("logical_path", metadata.get("source", ""))),
                document_id=str(metadata.get("document_id", "")),
                version=int(metadata.get("version", 1)),
                score=float(metadata.get("score", 0.0)),
            ))
        return results
