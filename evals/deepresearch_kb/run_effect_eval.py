"""Offline four-arm routing effect smoke test over the controlled dataset."""
import asyncio, json
from pathlib import Path
from deepresearch_kb.adaptive import AdaptiveResearchRouter
from deepresearch_kb.models import Evidence
from deepresearch_kb.sufficiency import EvidenceRequirement

async def evaluate():
    data=json.loads(Path(__file__).with_name("effect_dataset.json").read_text()); rows=[]
    for case in data["cases"]:
        def evidence(text, source):
            return [Evidence(source, text, "local_import" if source=="internal" else "external_web", f"fixture://{source}", source, source, 1, 1)] if text else []
        req=EvidenceRequirement(case["id"], tuple(case["required_claims"]), tuple("local_import" if s=="internal" else "external_web" for s in case["expected_sources"]), 1)
        async def quick(q): return evidence(case["external"], "external")
        async def deep(q): return evidence(case["external"] + " Deep research context.", "deep")
        router=AdaptiveResearchRouter(quick_search=quick, deep_research=deep, requirements=[req])
        conflict=case["id"]=="conflict_escalation"
        route, collected, decisions=await router.run(case["question"], internal=evidence(case["internal"], "internal"), conflict=conflict)
        rows.append({"id":case["id"],"expected":case["expected_route"],"actual":route,"passed":route==case["expected_route"],"evidence_count":len(collected),"decisions":[d.reason for d in decisions]})
    return {"evaluation":"effect-routing-v1","passed":sum(r["passed"] for r in rows),"total":len(rows),"results":rows,"scope":"controlled synthetic evidence; no LLM/network"}
if __name__=="__main__": print(json.dumps(asyncio.run(evaluate()),ensure_ascii=False,indent=2))
