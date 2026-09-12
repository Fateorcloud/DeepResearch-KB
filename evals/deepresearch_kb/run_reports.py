"""Real LLM comparison on frozen evidence, including upstream Hybrid workflow.

No claim of live-search benchmark: external retriever results are replayed for
every arm. Upstream Hybrid still plans, loads local files, compresses and writes.
"""

import argparse
import asyncio
import contextlib
import hashlib
import io
import json
import re
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.metrics import UsageCollector, attach_usage
from deepresearch_kb.research import ResearchOrchestrator, _external_evidence, render_evidence_context
from deepresearch_kb.run_research import live_factory

WRITING_PROMPT = """Answer the exact research question below in English, at most 180 words.
Use only the supplied context. If requested facts are missing, explicitly say they are unavailable.
Distinguish current vs deprecated documents and internal decisions vs external facts.
Every factual bullet must cite its supporting Source using a Markdown hyperlink.
Do not add unsupported facts or a generic background section.\nQuestion: """


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def score_presence(case, report, allowed):
    # Diagnostics only. Regex is NOT an entailment judge; manual review follows.
    links = re.findall(r"\]\(([^\s)]+)\)", report)
    return {"fact_mentions": {f["id"]: bool(re.search(f["pattern"], report, re.I)) for f in case["facts"]},
            "citation_links": links, "unknown_citation_links": sorted(set(links) - set(allowed)),
            "metric_note": "Keyword mentions and URI membership, not factual correctness or citation support."}


async def evaluate(output):
    raw = Path(__file__).with_name("report_cases.json").read_bytes()
    dataset = json.loads(raw)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    corpus = output / "corpus"
    corpus.mkdir()
    store = KnowledgeStore(output / "kb.sqlite")
    kb = store.create_knowledge_base("Boreal controlled corpus")
    for doc in dataset["documents"]:
        file = corpus / doc["file"]
        file.write_text(doc["text"], encoding="utf-8")
        await store.ingest(kb.id, file, logical_path=doc["logical_path"],
                           source_uri=f"fixture://boreal/{doc['file']}")
    write_json(output / "dataset.json", dataset)
    manifest = {"dataset_sha256": hashlib.sha256(raw).hexdigest(),
                "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "worktree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()),
                "upstream_commit": "6f998577d547b1e54ec662dac63583aa11e3b84b",
                "protocol": "frozen-excerpt replay; real LLM; upstream Hybrid vs KB-only vs project Hybrid",
                "results": []}
    write_json(output / "manifest.json", manifest)

    for case in dataset["cases"]:
        for arm in ("upstream_hybrid_replay", "kb_only", "project_hybrid"):
            print(f"Starting {case['id']} / {arm}", flush=True)
            folder = output / case["id"] / arm
            folder.mkdir(parents=True)
            usage = UsageCollector()
            counters = {"retriever_calls": 0}
            instances = []

            class RecordedRetriever:
                requires_scraping = False
                def __init__(self, query, **kwargs):
                    self.query = query
                def search(self, max_results=5):
                    counters["retriever_calls"] += 1
                    return [{"href": d["url"], "body": d["raw_content"], "raw_content": d["raw_content"]}
                            for d in dataset["external"][:max_results]]

            def factory(query):
                researcher = live_factory(query)
                researcher.retrievers = [RecordedRetriever]
                researcher.cfg.max_iterations = 1
                researcher.cfg.max_search_results_per_query = 2
                researcher.cfg.curate_sources = False
                researcher.cfg.total_words = 180
                researcher.cfg.smart_token_limit = 2500
                researcher.cfg.strategic_token_limit = 2500
                attach_usage(researcher, usage)
                instances.append(researcher)
                return researcher

            class External:
                async def search(self, query):
                    # Same exact snapshot as upstream's external retriever.
                    return _external_evidence(RecordedRetriever(query).search())

            started = time.perf_counter()
            record = {"case_id": case["id"], "arm": arm, "status": "running",
                      "actual_cost_usd": None, "live_search_calls": 0}
            try:
                async def execute():
                    if arm == "upstream_hybrid_replay":
                        researcher = factory(case["query"])
                        researcher.report_source = "hybrid"
                        researcher.report_generator.research_params["report_source"] = "hybrid"
                        researcher.cfg.doc_path = str(corpus.resolve())
                        context = await researcher.conduct_research()
                        sources = ([{"source_uri": d["file"], "text": d["text"], "type": "internal"}
                                    for d in dataset["documents"]] +
                                   [{"source_uri": d["url"], "text": d["raw_content"], "type": "external"}
                                    for d in dataset["external"]])
                        allowed = [s["source_uri"] for s in sources]
                    else:
                        mode = "internal" if arm == "kb_only" else "hybrid"
                        evidence = await ResearchOrchestrator(store, External()).research(
                            case["query"], mode=mode, knowledge_base_ids=[kb.id])
                        context = render_evidence_context(evidence)
                        sources = [asdict(e) for e in evidence]
                        from deepresearch_kb.research import citation_uri
                        allowed = [citation_uri(e) for e in evidence]
                        researcher = factory(case["query"])
                    (folder / "context.txt").write_text(str(context), encoding="utf-8")
                    write_json(folder / "sources.json", sources)
                    record["models"] = {key: getattr(researcher.cfg, key) for key in
                                        ("smart_llm_model", "strategic_llm_model", "smart_token_limit", "max_iterations")}
                    report = (await researcher.write_report(ext_context=context,
                              custom_prompt=WRITING_PROMPT + case["query"]) if context else
                              "Requested facts are unavailable: no evidence retrieved.")
                    if not report.strip():
                        raise ValueError("empty report")
                    (folder / "report.md").write_text(report, encoding="utf-8")
                    record.update(score_presence(case, report, allowed))
                # GPTR can print long contexts; keep console concise and avoid storing
                # unfiltered provider exceptions. Inputs are already explicitly saved.
                with contextlib.redirect_stdout(io.StringIO()):
                    await asyncio.wait_for(execute(), timeout=240)
                record["status"] = "completed"
            except Exception as exc:
                record["status"] = "failed"
                record["error_type"] = type(exc).__name__
            finally:
                record["latency_seconds"] = time.perf_counter() - started
                record.update(usage.summary())
                record.update(counters)
                record["upstream_estimate_usd_not_billing"] = sum(r.get_costs() for r in instances)
                write_json(folder / "metrics.json", record)
                manifest["results"].append(record)
                write_json(output / "manifest.json", manifest)
            print(f"Finished {case['id']} / {arm}: {record['status']}, {record['latency_seconds']:.1f}s", flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New directory; existing results are never overwritten")
    args = parser.parse_args()
    load_dotenv()
    import os
    if not os.getenv("OPENAI_API_KEY"):
        parser.error("Missing local model credentials")
    result = asyncio.run(evaluate(args.output))
    raise SystemExit(0 if all(r["status"] == "completed" for r in result["results"]) else 1)


if __name__ == "__main__":
    main()
