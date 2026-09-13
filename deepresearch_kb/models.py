"""Metadata shared by local import and files staged by a future upload endpoint."""

from dataclasses import dataclass
from typing import Literal

SourceType = Literal["local_import", "web_upload", "external_web"]


@dataclass(frozen=True)
class KnowledgeBase:
    id: str
    name: str
    created_at: str


@dataclass(frozen=True)
class DocumentVersion:
    knowledge_base_id: str
    document_id: str
    logical_path: str
    version: int
    source_type: SourceType
    source_uri: str
    content_hash: str
    updated_at: str
    ingested_at: str
    status: str
    pages: tuple[dict, ...]


@dataclass(frozen=True)
class Evidence:
    chunk_id: str
    text: str
    source_type: SourceType
    source_uri: str
    logical_path: str
    document_id: str
    version: int
    score: float
    knowledge_base_id: str | None = None
    content_hash: str | None = None
    updated_at: str | None = None
    effective_at: str | None = None
    status: str | None = None
    authority: int = 0
    version_selection_reason: str | None = None
    effective_at_inferred: bool | None = None
