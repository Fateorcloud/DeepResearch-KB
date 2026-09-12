"""Optional LangChain vector-index Adapter for persisted KB chunks."""

from typing import Any

from .models import Evidence


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
