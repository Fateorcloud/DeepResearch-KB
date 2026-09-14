"""Run the frozen Phase 4.5 real-project-style routing evaluation.

This runner is deliberately offline. It uses real SQLite/version governance and
the project Adaptive router, while Quick/Deep and synthesis are frozen adapters.
Fixture calls are not provider billing and no answer-quality claim is inferred.
"""
import argparse
import asyncio
import hashlib
import json
import shutil
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from deepresearch_kb.engine import ResearchEngine
from deepresearch_kb.governance import VersionGovernance
from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.models import Evidence
from deepresearch_kb.research import render_evidence_context
from deepresearch_kb.sufficiency import EvidenceRequirement, assess_requirements


ROOT = Path(__file__).resolve().parents[2]
DATASET = Path(__file__).with_name("phase45_cases.json")
AS_OF = datetime(2026, 9, 14, tzinfo=timezone.utc)


def load_dataset():
    raw = DATASET.read_bytes()
    data = json.loads(raw)
    if data.get("schema") != 1 or len(data.get("cases", [])) != 12:
        raise ValueError("Phase 4.5 dataset must contain exactly 12 schema-v1 cases")
    required = {"internal_architecture", "external_serverless", "stale_metadata_engine",
                "conflicting_writer_budget", "unknown_quantum_policy", "long_multi_requirement"}
    ids = {case["id"] for case in data["cases"]}
    if not required <= ids or len(ids) != len(data["cases"]):
        raise ValueError("dataset case identity/uniqueness check failed")
    for case in data["cases"]:
        if case.get("answerable") is None or not case.get("required_claims"):
            raise ValueError(f"incomplete gold contract: {case.get('id')}")
        if case.get("expected_route") not in ("stop", "quick", "deep"):
            raise ValueError(f"invalid expected route: {case.get('id')}")
    return data, raw


async def make_store(case, work):
    async def loader(path):
        return [{"raw_content": path.read_text(encoding="utf-8"), "url": path.name}]

    store = KnowledgeStore(work / "kb.sqlite", loader=loader)
    kb = store.create_knowledge_base(case["id"])
    created = {}
    for index, item in enumerate(case.get("internal_versions", [])):
        logical = item["logical_path"]
        file_name = f"doc-{index}.txt"
        path = work / file_name
        path.write_text(item["text"], encoding="utf-8")
        version = await store.ingest(
            kb.id, path, logical_path=logical, source_uri=item["source_uri"],
            updated_at=datetime.fromisoformat(item["effective_at"]))
        VersionGovernance(store).set_metadata(
            version.document_id, version.version,
            effective_at=datetime.fromisoformat(item["effective_at"]))
        created[(logical, version.version)] = version
    return store, kb, created


def requirement(case):
    return EvidenceRequirement(
        case["id"], tuple(case["required_claims"]),
        tuple(case.get("required_source_types", [])),
        int(case.get("minimum_distinct_sources", 1)),
        bool(case.get("require_current_version", True)),
    )


def external_evidence(case, stage):
    rows = []
    for index, item in enumerate(case.get(stage, [])):
        rows.append(Evidence(
            f"{case['id']}:{stage}:{index}", item["text"], "external_web",
            item["source_uri"], item["source_uri"], "", 1, 1.0,
            None, None, None, None, None, 0, None, None))
    return rows


class FixtureResearcher:
    def __init__(self, case):
        self.case = case

    @property
    def research_conductor(self):
        return self

    async def plan_research(self, query):
        if query != self.case["question"]:
            raise ValueError("fixture planner received a different query")
        return [self.case["subquestion"]]

    async def write_report(self, *, ext_context):
        return "FROZEN SYNTHESIS\n" + ext_context


class FixtureConflictChecker:
    def __init__(self, case):
        self.case = case

    async def check(self, evidence):
        if self.case.get("conflict") and len(evidence) >= 2:
            return {"status": "reviewed", "conflict_detected": True,
                    "pairs": [{"verdict": "conflict"}]}
        return {"status": "reviewed", "conflict_detected": False, "pairs": []}


def limitation_context(context, terminal_status):
    if terminal_status in ("unknown", "conflict", "insufficient"):
        return context + ("\n\nResearch limitations: frozen evaluation evidence is unresolved; "
                          "do not infer a supported answer.\n")
    return context


async def run_fixed(case, store, kb, folder):
    governed = VersionGovernance(store)
    internal = governed.retrieve([kb.id], case["subquestion"], limit=10,
                                  as_of=AS_OF)
    quick = external_evidence(case, "quick")
    evidence = internal + quick
    req = requirement(case)
    checks = assess_requirements([req], evidence)
    terminal = "sufficient" if checks[0].satisfied else ("conflict" if case.get("conflict") else "insufficient")
    context = limitation_context(render_evidence_context(evidence), terminal)
    report = "FROZEN SYNTHESIS\n" + context if evidence else "No source evidence was retrieved; report generation skipped."
    trace = [{"question": case["subquestion"], "source_policy": "fixed_hybrid",
              "rationale": "Fixed Hybrid always retrieves governed internal evidence and frozen Quick evidence",
              "requirement": asdict(req), "internal_evidence": [asdict(e) for e in internal],
              "quick_evidence": [asdict(e) for e in quick], "deep_evidence": [],
              "conflict_reviews": [], "decisions": [{"route": "fixed_hybrid", "terminal_status": terminal,
                  "reason": "fixed arm does not adapt"}], "final_route": "fixed_hybrid",
              "final_evidence": [asdict(e) for e in evidence]}]
    metrics = {"arm": "fixed_hybrid", "status": "completed" if terminal == "sufficient" else "incomplete", "evidence_status": [terminal],
               "final_route_summary": ["fixed_hybrid"], "quick_calls": 1, "deep_calls": 0,
               "fixture_calls": {"internal": 1, "quick": 1, "deep": 0},
               "llm_calls_started": 0, "llm_tokens": None, "actual_cost_usd": None,
               "latency_seconds": 0.0, "usage_scope": "offline frozen adapters; no provider calls"}
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "run.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (folder / "plan.json").write_text(json.dumps({"query": case["question"], "questions": [case["subquestion"]]}, indent=2), encoding="utf-8")
    (folder / "trace.json").write_text(json.dumps(trace, indent=2), encoding="utf-8")
    (folder / "sources.json").write_text(json.dumps([asdict(e) for e in evidence], indent=2), encoding="utf-8")
    (folder / "report.md").write_text(report, encoding="utf-8")
    return metrics


async def run_adaptive(case, store, kb, folder):
    req = requirement(case)
    quick_calls = []
    deep_calls = []

    async def quick(query):
        quick_calls.append(query)
        return external_evidence(case, "quick")

    async def deep(query):
        deep_calls.append(query)
        return external_evidence(case, "deep")

    engine = ResearchEngine(
        store=store, quick_search=quick, deep_research=deep,
        researcher_factory=lambda query: FixtureResearcher(case),
        conflict_checker=FixtureConflictChecker(case), as_of=AS_OF,
        max_deep_calls=1)
    result = await engine.run(
        case["question"], knowledge_base_ids=[kb.id],
        requirements={case["subquestion"]: req},
        output_dir=folder)
    metrics = result["metrics"]
    metrics["fixture_calls"] = {"internal": 1 if case.get("internal_versions") else 0,
                                 "quick": len(quick_calls), "deep": len(deep_calls)}
    metrics["arm"] = "adaptive"
    metrics["expected_route"] = case["expected_route"]
    metrics["route_matches_gold"] = metrics["final_route_summary"] == [case["expected_route"]]
    metrics["actual_cost_usd"] = None
    (folder / "run.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


async def evaluate(output, keep_work=False):
    dataset, raw = load_dataset()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "dataset.json").write_bytes(raw)
    manifest = {"protocol": dataset["protocol"], "dataset_sha256": hashlib.sha256(raw).hexdigest(),
                "cases": len(dataset["cases"]), "arms": ["fixed_hybrid", "adaptive"],
                "scope": "offline routing and evidence plumbing; no provider calls or answer-quality score"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    rows = []
    work_root = Path(tempfile.mkdtemp(prefix="phase45-kb-"))
    try:
        for case in dataset["cases"]:
            for arm in ("fixed_hybrid", "adaptive"):
                case_work = work_root / case["id"] / arm
                case_work.mkdir(parents=True)
                store, kb, _ = await make_store(case, case_work)
                folder = output / case["id"] / arm
                started = time.perf_counter()
                metrics = (await run_fixed(case, store, kb, folder) if arm == "fixed_hybrid"
                           else await run_adaptive(case, store, kb, folder))
                metrics["total_runner_latency_seconds"] = time.perf_counter() - started
                (folder / "run.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
                rows.append({"id": case["id"], "split": case["split"], "category": case["category"],
                             "arm": arm, "expected_route": case["expected_route"],
                             "answerable": case["answerable"], "metrics": metrics})
    finally:
        if not keep_work:
            shutil.rmtree(work_root, ignore_errors=True)
    summary = {"dataset_sha256": manifest["dataset_sha256"], "rows": rows,
               "aggregate": {arm: {
                   "cases": sum(1 for r in rows if r["arm"] == arm),
                   "adaptive_route_matches": sum(1 for r in rows if r["arm"] == arm and r["metrics"].get("route_matches_gold", False)),
                   "quick_calls": sum(r["metrics"].get("quick_calls", 0) for r in rows if r["arm"] == arm),
                   "deep_calls": sum(r["metrics"].get("deep_calls", 0) for r in rows if r["arm"] == arm),
                   "incomplete": sum(1 for r in rows if r["arm"] == arm and r["metrics"].get("status") == "incomplete")
               } for arm in ("fixed_hybrid", "adaptive")},
               "quality_note": "Routing and evidence plumbing only; report answer quality requires a separate paired judge/manual review."}
    (output / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--keep-work", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(evaluate(args.output, keep_work=args.keep_work))
    for arm, metrics in result["aggregate"].items():
        print(arm, metrics)


if __name__ == "__main__":
    main()
