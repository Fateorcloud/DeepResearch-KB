"""Frozen two-arm routing comparison. Fixture calls are not provider billing."""

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from deepresearch_kb.adaptive import AdaptiveResearchRouter
from deepresearch_kb.models import Evidence
from deepresearch_kb.sufficiency import EvidenceRequirement, assess_requirements


def evidence_for(case, stage):
    internal = stage == "internal"
    return [Evidence(
        f"{case['id']}:{stage}:{index}", text,
        "local_import" if internal else "external_web",
        f"fixture://{case['id']}/{stage}/{0 if internal and case.get('duplicate_internal_source') else index}",
        stage, f"{case['id']}:{stage}", 1, 1.0,
        status=case.get("internal_status", "active") if internal else None,
        effective_at="inferred-from-fixture" if internal and case.get("internal_status") else None,
        version_selection_reason="fixture marks this internal evidence superseded" if internal and case.get("internal_status") else None,
    ) for index, text in enumerate(case[stage])]


async def evaluate():
    raw = Path(__file__).with_name("effect_cases_v2.json").read_bytes()
    data = json.loads(raw)
    rows = []
    for case in data["cases"]:
        requirement = EvidenceRequirement(case["id"], tuple(case["required_claims"]),
            tuple(case.get("required_source_types", [])), case.get("minimum_distinct_sources", 1), True)
        for arm in ("fixed_hybrid", "adaptive"):
            calls = {"internal": 1, "quick": 0, "deep": 0}
            async def quick(query):
                calls["quick"] += 1
                return evidence_for(case, "quick")
            async def deep(query):
                calls["deep"] += 1
                return evidence_for(case, "deep")
            internal = evidence_for(case, "internal")
            if arm == "fixed_hybrid":
                evidence = internal + await quick(case["question"])
                route, decisions = "quick", []
            else:
                route, evidence, decisions = await AdaptiveResearchRouter(
                    quick_search=quick, deep_research=deep, requirements=[requirement]).run(
                        case["question"], internal=internal, conflict=case.get("conflict", False))
            checks = assess_requirements([requirement], evidence)
            terminal = decisions[-1].terminal_status if decisions else None
            if terminal is None:
                terminal = "sufficient" if checks[0].satisfied else "insufficient"
            rows.append({"id": case["id"], "split": case["split"], "arm": arm,
                "route": route, "expected_route": case["expected_route"],
                "route_matches_gold": route == case["expected_route"],
                "terminal_status": terminal, "answerable_gold": case["answerable"],
                "sufficient_on_unanswerable": terminal == "sufficient" and not case["answerable"],
                "calls": calls, "decisions": [asdict(d) for d in decisions],
                "evidence": [asdict(e) for e in evidence], "checks": [asdict(c) for c in checks]})
    return {"dataset_sha256": hashlib.sha256(raw).hexdigest(), "results": rows,
            "scope": "Frozen fixture routing comparison; no generated answers, semantic scores, network or token billing"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    result = asyncio.run(evaluate())
    with path.open("x", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    for arm in ("fixed_hybrid", "adaptive"):
        rows = [r for r in result["results"] if r["arm"] == arm]
        print(arm, {"cases": len(rows), "route_matches": sum(r["route_matches_gold"] for r in rows),
                    "sufficient_on_unanswerable": sum(r["sufficient_on_unanswerable"] for r in rows),
                    "quick_calls": sum(r["calls"]["quick"] for r in rows),
                    "deep_calls": sum(r["calls"]["deep"] for r in rows)})


if __name__ == "__main__":
    main()
