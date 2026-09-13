"""Explicit internal/external evidence orchestration."""
from typing import Any, Literal
import hashlib
from .models import Evidence
from .planning import PlannedEvidence, ResearchPlan
ResearchMode = Literal["internal", "external", "hybrid"]

def citation_uri(item: Evidence) -> str:
    if item.source_type == "external_web":
        return item.source_uri
    return f"kb://{item.document_id}/versions/{item.version}/chunks/{item.chunk_id}"

def render_evidence_context(evidence: list[Evidence]) -> str:
    """Render evidence for upstream synthesis without losing provenance."""
    blocks = []
    for index, item in enumerate(evidence, 1):
        label = "Internal Source" if item.source_type in ("local_import", "web_upload") else "External Source"
        provenance = (f"\nVersion: {item.version}\nChunk: {item.chunk_id}"
                      if label == "Internal Source" else "")
        if item.version_selection_reason is not None:
            provenance += (f"\nEffective at: {item.effective_at}\nStatus: {item.status}"
                           f"\nAuthority: {item.authority}\nSelection: {item.version_selection_reason}"
                           f"\nEffective time inferred: {item.effective_at_inferred}")
        blocks.append(f"[{index}] {label}\nSource: {citation_uri(item)}\nOrigin URI: {item.source_uri}\nDocument: {item.logical_path}{provenance}\nContent:\n{item.text}")
    return "\n\n---\n\n".join(blocks)


def render_planned_context(planned: list[PlannedEvidence]) -> str:
    """Render planned evidence grouped by sub-question and declared policy."""
    blocks = []
    for index, item in enumerate(planned, 1):
        block = render_evidence_context([item.evidence])
        blocks.append(f"## Planned Question {index}\nQuestion: {item.question}\nSource Policy: {item.source_policy}\n\n{block}")
    return "\n\n=== SUB-QUESTION ===\n\n".join(blocks)
def _external_evidence(results: list[dict[str, Any]]) -> list[Evidence]:
    output = []
    for index, result in enumerate(results):
        if not isinstance(result, dict): continue
        text = result.get("body") or result.get("content") or result.get("raw_content") or ""
        uri = result.get("href") or result.get("url") or ""
        if isinstance(text, str) and isinstance(uri, str) and text.strip() and uri.startswith(("https://", "http://")):
            identity = hashlib.sha256((uri + "\n" + text).encode()).hexdigest()[:20]
            output.append(Evidence(f"external-{identity}", text, "external_web", uri, uri, "", 1, 0.0))
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
        if not query.strip() or limit < 1:
            raise ValueError("non-empty query and positive limit required")
        if mode != "external" and not knowledge_base_ids:
            raise ValueError("internal/hybrid requires explicit knowledge_base_ids")
        internal = self.knowledge_store.retrieve(knowledge_base_ids or [], query, limit=limit) if mode != "external" else []
        if mode == "internal": return internal
        if self.external_research is None: raise ValueError("external_research is required for external or hybrid mode")
        return (internal + (await self.external_research.search(query))[:limit])[:limit * 2]

    async def execute_plan(self, plan: ResearchPlan, *, knowledge_base_ids=None, limit: int = 5) -> list[PlannedEvidence]:
        """Execute each planned question with its declared source policy."""
        output = []
        for item in plan.questions:
            evidence = await self.research(item.question, mode=item.source_policy,
                                           knowledge_base_ids=knowledge_base_ids, limit=limit)
            output.extend(PlannedEvidence(item.question, item.source_policy, entry) for entry in evidence)
        return output

    async def write_planned_report(self, plan: ResearchPlan, *, researcher_factory,
                                   knowledge_base_ids=None, limit: int = 5,
                                   **report_options) -> tuple[str, list[PlannedEvidence]]:
        """Execute a plan and delegate grouped evidence to upstream synthesis."""
        planned = await self.execute_plan(plan, knowledge_base_ids=knowledge_base_ids, limit=limit)
        if not planned:
            return "No source evidence was retrieved; report generation skipped.", []
        researcher = researcher_factory(plan.query)
        report = await researcher.write_report(ext_context=render_planned_context(planned), **report_options)
        return report, planned

    async def write_report(self, query: str, *, mode: ResearchMode,
                           researcher_factory, knowledge_base_ids=None,
                           limit: int = 5, **report_options) -> tuple[str, list[Evidence]]:
        """Run explicit evidence collection, then delegate synthesis upstream."""
        evidence = await self.research(query, mode=mode, knowledge_base_ids=knowledge_base_ids, limit=limit)
        if not evidence:
            return "No source evidence was retrieved; report generation skipped.", []
        researcher = researcher_factory(query)
        report = await researcher.write_report(ext_context=render_evidence_context(evidence), **report_options)
        return report, evidence
