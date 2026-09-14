from dataclasses import asdict
from pathlib import Path

from ..knowledge import KnowledgeStore


class KnowledgeService:
    def __init__(self, store: KnowledgeStore):
        self.store = store

    def create(self, name: str):
        return self.store.create_knowledge_base(name)

    def list(self):
        return self.store.list_knowledge_bases()

    async def ingest(self, kb_id, file_path, *, logical_path, source_type="web_upload", source_uri=None):
        return await self.store.ingest(kb_id, Path(file_path), logical_path=logical_path,
                                       source_type=source_type, source_uri=source_uri)

    def documents(self, kb_id):
        return self.store.list_documents(kb_id)

    def versions(self, kb_id, document_id):
        return self.store.list_versions_by_document(kb_id, document_id)

    def search(self, query, knowledge_base_ids, *, limit=5, as_of=None):
        from ..governance import VersionGovernance
        if not knowledge_base_ids:
            raise ValueError("knowledge_base_ids must not be empty")
        return VersionGovernance(self.store).retrieve(knowledge_base_ids, query, limit=limit, as_of=as_of)
