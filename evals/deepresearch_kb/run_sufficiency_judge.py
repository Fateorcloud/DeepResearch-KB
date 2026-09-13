"""Real two-case sufficiency judge check using synthetic evidence only."""
import argparse, asyncio, json, os, time
from pathlib import Path
from dotenv import load_dotenv
from deepresearch_kb.metrics import UsageCollector
from deepresearch_kb.models import Evidence
from deepresearch_kb.sufficiency import EvidenceRequirement, configured_sufficiency_judge

async def main(output):
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"): raise RuntimeError("model credentials required")
    usage=UsageCollector(); judge=configured_sufficiency_judge(usage)
    cases=[("satisfied", EvidenceRequirement("r",("SQLite is current",)), [Evidence("c","SQLite is current.","local_import","file:///a","a","d",1,1)]),
           ("missing", EvidenceRequirement("r",("PostgreSQL is current",)), [Evidence("c","SQLite is current.","local_import","file:///a","a","d",1,1)])]
    rows=[]
    for name,req,evidence in cases:
        start=time.perf_counter(); result=await judge.judge(req,evidence)
        rows.append({"id":name,"status":result["status"],"expected":"sufficient" if name=="satisfied" else "insufficient","passed":result["status"]==("sufficient" if name=="satisfied" else "insufficient"),"latency_seconds":time.perf_counter()-start,"result":result})
    payload={"cases":rows,"usage":usage.summary(),"scope":"synthetic evidence; one real model judge call per case; no search"}
    Path(output).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(payload,ensure_ascii=False,indent=2)); return payload
if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--output",required=True); a=p.parse_args(); result=asyncio.run(main(a.output)); raise SystemExit(0 if all(r["passed"] for r in result["cases"]) else 1)
