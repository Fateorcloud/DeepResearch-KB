# Phase 5A Product Interface Closure

Phase 5A adds a thin application boundary around the accepted Research Core. `KnowledgeService` delegates to `KnowledgeStore`; `ResearchService` delegates to `ResearchEngine`; HTTP and CLI do not reimplement parsing, retrieval, governance, routing, or synthesis.

Implemented interfaces:

- Standalone FastAPI app in `deepresearch_kb.api`
- KB create/list, upload, document/version listing
- Single-process asynchronous research tasks and artifact endpoints
- Recursive local `ingest-dir` and HTTP `push-dir`

Upload validation rejects traversal, empty files, and unsupported extensions. Uploads stage bytes in a temporary file, call the existing ingest contract with `source_type=web_upload`, and clean up staging. Hash idempotency and immutable version history remain in SQLite.

Verification: Phase 5A integration tests cover upload provenance, duplicate upload, version increment, path traversal, unsupported input, recursive directory import, skipped directories, and unchanged summaries. Existing core tests remain green. The executor is intentionally single-process: in-memory task state is lost on restart and no distributed queue or bidirectional sync is provided.
