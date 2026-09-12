"""Explicit internal/external evidence orchestration."""
from typing import Any, Literal
from .models import Evidence
ResearchMode = Literal["internal", "external", "hybrid"]

def render_evidence_context(evidence: list[Evidence]) -> str:
    """Render evidence for upstream synthesis without losing provenance."""
    blocks = []
    for index, item in enumerate(evidence, 1):
        label = "Internal Source" if item.source_type in ("local_import", "web_upload") else "External Source"
        blocks.append(f"[{index}] {label}\nSource: {item.source_uri}\nDocument: {item.logical_path}\nVersion: {item.version}\nContent:\n{item.text}")
    return "\n\n---\n\n".join(blocks)
def _external_evidence(results: list[dict[str, Any]]) -> list[Evidence]:
    output = []
    for index, result in enumerate(results):
        if not isinstance(result, dict): continue
        text = result.get("body") or result.get("content") or result.get("raw_content") or ""
        uri = result.get("href") or result.get("url") or ""
        if str(text).strip() and str(uri).strip():
            output.append(Evidence(f"external-{index}", str(text), "external_web", str(uri), str(uri), "", 1, 0.0))
    return output
class UpstreamExternalResearch:
    def __init__(self, researcher_factory): self.researcher_factory = researcher_factory
    async def search(self, query: str) -> list[Evidence]:
        researcher = self.researcher_factory(query)
        results = await researcher.quick_search(query)
        return _external_evidence(results if isinstance(results, list) else [])
class ResearchOrchestrator:
    def __init__(self, knowledge_store, external_research=None):
        self.knowledge_store, self.external_research = knowledge_store, external_research
    async def research(self, query: str, *, mode: ResearchMode, knowledge_base_ids=None, limit: int = 5) -> list[Evidence]:
        if mode not in ("internal", "external", "hybrid"): raise ValueError("mode must be internal, external, or hybrid")
        internal = self.knowledge_store.retrieve(knowledge_base_ids or [], query, limit=limit) if mode != "external" else []
        if mode == "internal": return internal
        if self.external_research is None: raise ValueError("external_research is required for external or hybrid mode")
        return (internal + (await self.external_research.search(query))[:limit])[:limit * 2]
