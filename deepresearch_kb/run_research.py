"""Explicit live quick-search/synthesis runner; no adaptive or deep research."""

import argparse
import asyncio
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from .knowledge import KnowledgeStore
from .research import ResearchOrchestrator, UpstreamExternalResearch


def live_factory(query):
    from gpt_researcher import GPTResearcher

    return GPTResearcher(
        query=query, report_type="research_report", report_source="web",
        agent="Research analyst", role="Synthesize only the provided evidence and cite its sources.",
        verbose=False, mcp_strategy="disabled",
    )


async def run(store, query, *, mode, kb_ids, output_dir, researcher_factory=live_factory):
    """Save only an allowlisted manifest, never environment or provider kwargs."""
    directory = Path(output_dir) / uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    instances = []

    def factory(question):
        instance = researcher_factory(question)
        instances.append(instance)
        return instance

    start = time.perf_counter()
    manifest = {"query": query, "mode": mode, "knowledge_base_ids": kb_ids,
                "status": "running", "llm_tokens": None, "search_cost_usd": None,
                "research_path": "quick_search + synthesis; no deep research"}
    try:
        orchestrator = ResearchOrchestrator(store, UpstreamExternalResearch(factory))
        report, evidence = await orchestrator.write_report(
            query, mode=mode, knowledge_base_ids=kb_ids, researcher_factory=factory,
        )
        if evidence and not report.strip():
            raise ValueError("upstream returned empty report")
        (directory / "report.md").write_text(report, encoding="utf-8")
        (directory / "sources.json").write_text(
            json.dumps([asdict(item) for item in evidence], ensure_ascii=False, indent=2), encoding="utf-8")
        manifest["status"] = "completed" if evidence else "no_evidence"
        manifest["evidence_count"] = len(evidence)
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error_type"] = type(exc).__name__  # exception text can contain credentials
        raise
    finally:
        manifest["latency_seconds"] = time.perf_counter() - start
        costs = [item.get_costs() for item in instances if hasattr(item, "get_costs")]
        manifest["upstream_reported_cost_usd"] = sum(costs) if costs else None
        manifest["cost_note"] = "Upstream-reported only; not total billing. Unknown metrics remain null."
        (directory / "run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return directory


def main():
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--mode", choices=["internal", "external", "hybrid"], required=True)
    parser.add_argument("--kb", action="append", default=[])
    parser.add_argument("--database", default="data/kb.sqlite")
    parser.add_argument("--output", default="data/runs")
    args = parser.parse_args()
    if args.mode != "external" and not args.kb:
        parser.error("internal/hybrid requires --kb")
    load_dotenv()
    required = ["OPENAI_API_KEY"] + (["TAVILY_API_KEY"] if args.mode != "internal" else [])
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        parser.error("Missing local credentials: " + ", ".join(missing))
    print(asyncio.run(run(KnowledgeStore(args.database), args.query, mode=args.mode,
                         kb_ids=args.kb, output_dir=args.output)))


if __name__ == "__main__":
    main()
