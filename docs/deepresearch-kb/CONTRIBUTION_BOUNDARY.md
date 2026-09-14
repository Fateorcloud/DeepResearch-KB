# Upstream vs DeepResearch-KB

## Reused from GPT Researcher

- Web, Quick and Deep research; upstream sub-query planning
- `DocumentLoader`, report synthesis, citations and provider abstraction
- Local/Hybrid primitives, vector adapters and upstream MCP client/retriever capability

## Implemented or extended here

- Persistent SQLite KnowledgeBase, Document, DocumentVersion and Chunk lifecycle
- Content-hash idempotency, immutable provenance and KB citation metadata
- Source-policy planning and current/as-of/deprecated version governance
- Evidence requirements, sufficiency gates and STOP/Quick/Deep adaptive orchestration
- Conflict/unknown safety behavior and unified `ResearchEngine` artifacts
- Evaluation harness, Service Layer, FastAPI, Web Upload, `ingest-dir`, `push-dir` and task abstraction
- Thin MCP facade exposing project services to external agents

The project does not claim to have implemented GPT Researcher, generic RAG, vector databases, Deep Research, or MCP from scratch.
