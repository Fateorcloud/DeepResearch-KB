"""Verify that planned policies produce the intended adapter calls."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from deepresearch_kb.models import Evidence
from deepresearch_kb.planning import RuleBasedSourcePlanner
from deepresearch_kb.research import ResearchOrchestrator


async def evaluate():
    cases = json.loads(Path(__file__).with_name("source_planning_cases.json").read_text())['cases']
    counts = {"internal": 0, "external": 0}
    internal = Evidence("i", "internal", "local_import", "file:///i", "i", "d", 1, 1.0)
    external = Evidence("e", "external", "external_web", "https://e", "https://e", "", 1, 1.0)

    class Store:
        def retrieve(self, ids, query, limit):
            counts["internal"] += 1
            return [internal]

    class External:
        async def search(self, query):
            counts["external"] += 1
            return [external]

    planner = RuleBasedSourcePlanner()
    results = []
    for case in cases:
        before = counts.copy()
        planned = planner.plan(case["query"])
        await ResearchOrchestrator(Store(), External()).execute_plan(planned, knowledge_base_ids=["kb"])
        delta = {key: counts[key] - before[key] for key in counts}
        expected = {"internal": int(case["policy"] in ("internal", "hybrid")),
                    "external": int(case["policy"] in ("external", "hybrid"))}
        results.append({"id": case["id"], "policy": case["policy"], "calls": delta,
                        "expected_calls": expected, "passed": delta == expected})
    return {"evaluation": "source-planning-execution-v1", "total": len(results),
            "passed": sum(row["passed"] for row in results), "results": results,
            "scope": "fake adapters; no LLM/network; call routing only"}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(evaluate()), ensure_ascii=False, indent=2))
