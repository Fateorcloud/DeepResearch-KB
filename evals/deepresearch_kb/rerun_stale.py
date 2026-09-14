"""Re-synthesize only stale holdout reports after governance-warning fix."""
import argparse, asyncio, json, time
from pathlib import Path
from dotenv import load_dotenv
from gpt_researcher import GPTResearcher
from deepresearch_kb.metrics import UsageCollector, attach_usage
from deepresearch_kb.models import Evidence
from deepresearch_kb.research import render_evidence_context

PROMPT="""Answer the question using only supplied evidence. Distinguish superseded internal evidence from current evidence; if current status cannot be established, say so. Cite every factual statement with supplied URIs. Return at most 120 words. Question: """
async def main(output):
    load_dotenv(); root=Path("data/evals/effect-v2-reports-1/holdout_stale"); out=Path(output); out.mkdir(parents=True,exist_ok=False); results=[]
    for arm in ("fixed_hybrid","adaptive"):
        source=json.loads((root/arm/"sources.json").read_text()); evidence=[Evidence(**item) for item in source]
        context=render_evidence_context(evidence); context += "\n\nWARNING: Superseded internal evidence is historical and cannot establish the current engine."
        usage=UsageCollector(); researcher=GPTResearcher(query="What is Aurora's current metadata engine?", report_source="web", verbose=False, mcp_strategy="disabled"); attach_usage(researcher,usage)
        start=time.perf_counter(); report=await researcher.write_report(ext_context=context, custom_prompt=PROMPT+"What is Aurora's current metadata engine?")
        folder=out/arm; folder.mkdir(); (folder/"report.md").write_text(report); (folder/"context.txt").write_text(context)
        results.append({"arm":arm,"status":"completed","latency_seconds":time.perf_counter()-start,"usage":usage.summary()})
    (out/"metrics.json").write_text(json.dumps({"results":results,"scope":"stale holdout re-synthesis after warning fix"},indent=2)); print(json.dumps(results,indent=2))
if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--output",required=True); a=p.parse_args(); asyncio.run(main(a.output))
