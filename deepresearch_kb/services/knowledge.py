from dataclasses import dataclass
from pathlib import Path

from ..knowledge import KnowledgeStore


def _parsed_content(version):
    return "\n\n".join(page["raw_content"].strip() for page in version.pages
                        if page.get("raw_content", "").strip())


@dataclass(frozen=True)
class DocumentPreview:
    document_id: str
    knowledge_base_id: str
    logical_path: str
    current_version: int
    version_count: int
    source_type: str
    source_uri: str
    content_hash: str
    updated_at: str
    ingested_at: str
    status: str
    parsed_content_preview: str
    preview_truncated: bool


@dataclass(frozen=True)
class DocumentVersionDetail:
    document_id: str
    knowledge_base_id: str
    logical_path: str
    version: int
    source_type: str
    source_uri: str
    content_hash: str
    updated_at: str
    ingested_at: str
    status: str
    parsed_content: str


class KnowledgeService:
    def __init__(self, store: KnowledgeStore):
        self.store = store

    def create(self, name: str):
        return self.store.create_knowledge_base(name)

    def list(self):
        return self.store.list_knowledge_bases()

    def rename(self, kb_id, name):
        return self.store.rename_knowledge_base(kb_id, name)

    async def ingest(self, kb_id, file_path, *, logical_path, source_type="web_upload", source_uri=None):
        return await self.store.ingest(kb_id, Path(file_path), logical_path=logical_path,
                                       source_type=source_type, source_uri=source_uri)

    def documents(self, kb_id):
        return self.store.list_documents(kb_id)

    def versions(self, kb_id, document_id):
        return self.store.list_versions_by_document(kb_id, document_id)

    def document(self, kb_id, document_id, *, preview_chars=4000):
        versions = self.versions(kb_id, document_id)
        current = next((version for version in reversed(versions)
                        if version.status == "active"), versions[-1])
        content = _parsed_content(current)
        return DocumentPreview(
            current.document_id, current.knowledge_base_id, current.logical_path,
            current.version, len(versions), current.source_type, current.source_uri,
            current.content_hash, current.updated_at, current.ingested_at,
            current.status, content[:preview_chars], len(content) > preview_chars)

    def version(self, kb_id, document_id, version):
        if type(version) is not int or version < 1:
            raise ValueError("version must be a positive integer")
        match = next((item for item in self.versions(kb_id, document_id)
                      if item.version == version), None)
        if match is None:
            raise KeyError(version)
        return DocumentVersionDetail(
            match.document_id, match.knowledge_base_id, match.logical_path,
            match.version, match.source_type, match.source_uri,
            match.content_hash, match.updated_at, match.ingested_at,
            match.status, _parsed_content(match))

    def search(self, query, knowledge_base_ids, *, limit=5, as_of=None):
        from ..governance import VersionGovernance
        if not knowledge_base_ids:
            raise ValueError("knowledge_base_ids must not be empty")
        return VersionGovernance(self.store).retrieve(knowledge_base_ids, query, limit=limit, as_of=as_of)
