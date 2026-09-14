"""Repeat frozen routing to verify deterministic stability."""
import asyncio
import json
from .run_effect_v2 import evaluate

async def main(repetitions=3):
    runs=[await evaluate() for _ in range(repetitions)]
    signatures=[[(r["id"],r["arm"],r["route"],r["calls"]) for r in run["results"]] for run in runs]
    summary=[]
    for arm in ("fixed_hybrid","adaptive"):
        rows=[r for r in runs[0]["results"] if r["arm"]==arm]
        summary.append({"arm":arm,"runs":repetitions,"route_matches":sum(r["route_matches_gold"] for r in rows),
                        "quick_calls":sum(r["calls"]["quick"] for r in rows),"deep_calls":sum(r["calls"]["deep"] for r in rows),
                        "deep_trigger_rate":sum(r["calls"]["deep"]>0 for r in rows)/len(rows)})
    return {"evaluation":"effect-routing-repeat-v1","repetitions":repetitions,"stable":all(s==signatures[0] for s in signatures[1:]),"summary":summary,"scope":"fixture only; no LLM/network/token"}

if __name__=="__main__": print(json.dumps(asyncio.run(main()),ensure_ascii=False,indent=2))
