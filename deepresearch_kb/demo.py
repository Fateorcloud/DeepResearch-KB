"""Offline Phase 1 demonstration using the real KB and fake external/reporter adapters."""
import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace

from .knowledge import KnowledgeStore
from .research import ResearchOrchestrator
from .models import Evidence


async def run_demo() -> str:
    with tempfile.TemporaryDirectory(prefix="deepresearch-kb-demo-") as directory:
        root = Path(directory)
        source = root / "upload.tmp"
        source.write_text("Project used PostgreSQL metadata. Deprecated version.", encoding="utf-8")
        store = KnowledgeStore(root / "kb.sqlite")
        kb = store.create_knowledge_base("Demo KB")
        await store.ingest(kb.id, source, logical_path="architecture/current.txt")
        source.write_text("Project uses SQLite metadata and a Python research pipeline. Current version.", encoding="utf-8")
        await store.ingest(kb.id, source, logical_path="architecture/current.txt")
        # New instance reads the persistent current version; no duplicate ingest.
        store = KnowledgeStore(root / "kb.sqlite")

        class External:
            async def search(self, query):
                return [Evidence("demo-external", "SQLite is serverless (fixed demo fixture, not a live search).",
                                 "external_web", "https://sqlite.org/about.html", "SQLite about", "", 1, 0.0)]

        class Reporter:
            async def write_report(self, *, ext_context, **kwargs):
                return "OFFLINE DEMO — reporter and external search are fixtures, NOT a real research report\n\n" + ext_context

        orchestrator = ResearchOrchestrator(store, External())
        report, evidence = await orchestrator.write_report(
            "SQLite", mode="hybrid", knowledge_base_ids=[kb.id],
            researcher_factory=lambda query: Reporter())
        return report + f"\n\nEvidence count: {len(evidence)}"


if __name__ == "__main__":
    print(asyncio.run(run_demo()))
