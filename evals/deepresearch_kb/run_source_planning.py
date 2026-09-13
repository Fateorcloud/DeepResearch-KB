"""Offline source-policy planner evaluation."""
import json
from pathlib import Path
from deepresearch_kb.planning import RuleBasedSourcePlanner


def evaluate(path=None):
    source = Path(path) if path else Path(__file__).with_name("source_planning_cases.json")
    data = json.loads(source.read_text(encoding="utf-8"))
    planner = RuleBasedSourcePlanner()
    rows = []
    for case in data["cases"]:
        planned = planner.plan(case["query"]).questions[0]
        rows.append({"id": case["id"], "expected": case["policy"], "actual": planned.source_policy,
                     "passed": planned.source_policy == case["policy"], "rationale": planned.rationale})
    return {"evaluation": "source-planning-baseline-v1", "total": len(rows),
            "passed": sum(row["passed"] for row in rows), "results": rows,
            "scope": "deterministic rules; no LLM; policy classification only"}


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
