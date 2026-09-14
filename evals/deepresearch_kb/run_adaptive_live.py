"""One real adaptive run: governed KB -> quick search -> optional deep research."""
import argparse, asyncio, json, os, time
from pathlib import Path
from dotenv import load_dotenv
from gpt_researcher import GPTResearcher
from deepresearch_kb.adaptive import AdaptiveResearchRouter
from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.research import UpstreamExternalResearch
from deepresearch_kb.deep_adapter import UpstreamDeepResearch
from deepresearch_kb.sufficiency import EvidenceRequirement

async def main(query, database, kb, output, max_deep_calls=1):
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY") or not os.getenv("TAVILY_API_KEY"): raise RuntimeError("local model/search credentials required")
    def factory(question): return GPTResearcher(query=question, report_source="web", verbose=False, mcp_strategy="disabled")
    store=KnowledgeStore(database); internal=store.retrieve([kb],query,limit=5)
    requirement = EvidenceRequirement("live-query", (query,), minimum_distinct_sources=1)
    external=UpstreamExternalResearch(factory); deep_calls=[]; quick_calls=[]
    async def quick(question): quick_calls.append(question); return await external.search(question)
    async def deep(question):
        deep_calls.append(question)
        return await UpstreamDeepResearch().search(question)
    started=time.perf_counter(); router=AdaptiveResearchRouter(quick_search=quick,deep_research=deep,max_deep_calls=max_deep_calls,requirements=[requirement])
    route,evidence,decisions=await router.run(query,internal=internal)
    folder=Path(output); folder.mkdir(parents=True,exist_ok=False)
    (folder/"route.json").write_text(json.dumps({"query":query,"final_route":route,"evidence_count":len(evidence),"quick_calls":len(quick_calls),"deep_calls":len(deep_calls),"max_deep_calls":max_deep_calls,"decisions":[d.__dict__ for d in decisions],"latency_seconds":time.perf_counter()-started},indent=2))
    print(folder)

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("query"); p.add_argument("--database",required=True); p.add_argument("--kb",required=True); p.add_argument("--output",required=True); p.add_argument("--max-deep-calls",type=int,default=1); a=p.parse_args(); asyncio.run(main(a.query,a.database,a.kb,a.output,a.max_deep_calls))
