"""Explicit live quick-search/synthesis runner; no adaptive or deep research."""

import argparse
import asyncio
import json
import os
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .knowledge import KnowledgeStore
from .research import ResearchOrchestrator, UpstreamExternalResearch
from .research import render_evidence_context
from .metrics import UsageCollector, attach_usage


def live_factory(query):
    from gpt_researcher import GPTResearcher

    return GPTResearcher(
        query=query, report_type="research_report", report_source="web",
        agent="Research analyst", role="Synthesize only the provided evidence and cite its sources.",
        verbose=False, mcp_strategy="disabled",
    )


async def run(store, query, *, mode, kb_ids, output_dir, researcher_factory=live_factory,
              governed=False, as_of=None, include_superseded=False, include_deprecated=False,
              conflict_checker=None, check_conflicts=False):
    """Save only an allowlisted manifest, never environment or provider kwargs."""
    policy = None
    if governed or as_of is not None or include_superseded or include_deprecated:
        if mode == "external":
            raise ValueError("version governance applies to internal evidence, not live external search")
        from .governance import GovernedKnowledge
        store = GovernedKnowledge(store, as_of=as_of, include_superseded=include_superseded,
                                  include_deprecated=include_deprecated)
        policy = {"as_of": store.as_of.isoformat(), "include_superseded": include_superseded,
                  "include_deprecated": include_deprecated,
                  "external_temporality": "live external evidence is not historical as-of evidence"}
    directory = Path(output_dir) / uuid4().hex
    directory.mkdir(parents=True, exist_ok=False)
    instances = []
    usage = UsageCollector()
    if check_conflicts and conflict_checker is None:
        from .conflicts import configured_conflict_checker
        conflict_checker = configured_conflict_checker(usage)

    def factory(question):
        instance = researcher_factory(question)
        if hasattr(instance, "cfg"):
            attach_usage(instance, usage)
        instances.append(instance)
        return instance

    start = time.perf_counter()
    manifest = {"query": query, "mode": mode, "knowledge_base_ids": kb_ids,
                "status": "running", "llm_tokens": None, "search_cost_usd": None,
                "actual_cost_usd": None,
                "research_path": {"internal": "KB retrieval + synthesis", "external": "quick_search + synthesis",
                                  "hybrid": "KB retrieval + quick_search + synthesis"}[mode],
                "search_calls": 0, "deep_research_calls": 0, "version_policy": policy}
    try:
        class External(UpstreamExternalResearch):
            async def search(self, question):
                manifest["search_calls"] += 1
                return await super().search(question)
        orchestrator = ResearchOrchestrator(store, External(factory))
        evidence = await orchestrator.research(query, mode=mode, knowledge_base_ids=kb_ids)
        from .conflicts import inspect_version_overlap
        warnings = [asdict(w) for w in inspect_version_overlap(evidence)]
        semantic = (await conflict_checker.check(evidence) if conflict_checker is not None else
                    {"status": "not_evaluated", "pairs": []})
        conflict_record = {"version_warnings": warnings, "semantic": semantic}
        (directory / "conflicts.json").write_text(json.dumps(
            conflict_record, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest["semantic_conflict_status"] = semantic["status"]
        context = render_evidence_context(evidence)
        if warnings:
            context += "\n\nVersion warnings (not factual verdicts):\n" + json.dumps(warnings, ensure_ascii=False)
        if conflict_checker is not None:
            context += ("\n\nFallible conflict review: preserve uncertainty; do not choose a winner "
                        "without supporting evidence. Unknown is not conflict-free.\n" +
                        json.dumps(semantic, ensure_ascii=False))
        if policy:
            context = "Internal version selection policy: " + json.dumps(policy) + "\n\n" + context
        # Preserve collected evidence even if synthesis fails.
        (directory / "context.txt").write_text(context, encoding="utf-8")
        (directory / "sources.json").write_text(
            json.dumps([asdict(item) for item in evidence], ensure_ascii=False, indent=2), encoding="utf-8")
        report = (await factory(query).write_report(ext_context=context) if evidence else
                  "No source evidence was retrieved; report generation skipped.")
        if evidence and not report.strip():
            raise ValueError("upstream returned empty report")
        (directory / "report.md").write_text(report, encoding="utf-8")
        (directory / "sources.json").write_text(
            json.dumps([asdict(item) for item in evidence], ensure_ascii=False, indent=2), encoding="utf-8")
        manifest["status"] = "completed" if evidence else "no_evidence"
        manifest["evidence_count"] = len(evidence)
    except BaseException as exc:
        manifest["status"] = "failed"
        manifest["error_type"] = type(exc).__name__  # exception text can contain credentials
        raise
    finally:
        manifest["latency_seconds"] = time.perf_counter() - start
        manifest.update(usage.summary())
        costs = [item.get_costs() for item in instances if hasattr(item, "get_costs")]
        manifest["upstream_reported_cost_usd"] = sum(costs) if costs else None
        manifest["cost_note"] = "Upstream estimate, NOT actual billing; especially invalid for DeepSeek via OpenAI pricing."
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
    parser.add_argument("--governed", action="store_true")
    parser.add_argument("--as-of", type=datetime.fromisoformat)
    parser.add_argument("--include-superseded", action="store_true")
    parser.add_argument("--include-deprecated", action="store_true")
    parser.add_argument("--check-conflicts", action="store_true", help="Additional model call; records uncertainty, never adjudicates")
    args = parser.parse_args()
    if args.mode != "external" and not args.kb:
        parser.error("internal/hybrid requires --kb")
    load_dotenv()
    llm_providers = {
        value.partition(":")[0]
        for value in (
            os.getenv("FAST_LLM", "openai:gpt-4o-mini"),
            os.getenv("SMART_LLM", "openai:gpt-4o"),
            os.getenv("STRATEGIC_LLM", "openai:o1-preview"),
        )
    }
    required = [
        {"openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}.get(
            provider, f"{provider.upper()}_API_KEY")
        for provider in sorted(llm_providers)
    ] + (["TAVILY_API_KEY"] if args.mode != "internal" else [])
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        parser.error("Missing local credentials: " + ", ".join(missing))
    print(asyncio.run(run(KnowledgeStore(args.database), args.query, mode=args.mode,
                         kb_ids=args.kb, output_dir=args.output, governed=args.governed,
                         as_of=args.as_of, include_superseded=args.include_superseded,
                         include_deprecated=args.include_deprecated, check_conflicts=args.check_conflicts)))


if __name__ == "__main__":
    main()
