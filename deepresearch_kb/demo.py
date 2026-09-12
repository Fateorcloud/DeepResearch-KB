"""Offline Phase 1 demonstration using the real KB and fake external/reporter adapters."""
import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace

from .knowledge import KnowledgeStore
from .research import ResearchOrchestrator


async def run_demo() -> str:
    with tempfile.TemporaryDirectory(prefix="deepresearch-kb-demo-") as directory:
        root = Path(directory)
        source = root / "upload.tmp"
        source.write_text("Project uses SQLite metadata and a Python research pipeline.", encoding="utf-8")
        store = KnowledgeStore(root / "kb.sqlite")
        kb = store.create_knowledge_base("Demo KB")
        await store.ingest(kb.id, source, logical_path="architecture/current.txt")

        class External:
            async def search(self, query):
                return []

        class Reporter:
            async def write_report(self, *, ext_context, **kwargs):
                return "DEMO REPORT\n\n" + ext_context

        orchestrator = ResearchOrchestrator(store, External())
        report, evidence = await orchestrator.write_report(
            "SQLite", mode="hybrid", knowledge_base_ids=[kb.id],
            researcher_factory=lambda query: Reporter())
        return report + f"\n\nEvidence count: {len(evidence)}"


if __name__ == "__main__":
    print(asyncio.run(run_demo()))
