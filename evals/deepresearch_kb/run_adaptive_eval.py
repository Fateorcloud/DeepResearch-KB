import asyncio,json
from pathlib import Path
from deepresearch_kb.adaptive import AdaptiveResearchRouter
from deepresearch_kb.models import Evidence
async def evaluate():
 cases=json.loads(Path(__file__).with_name("adaptive_cases.json").read_text())["cases"]; rows=[]
 for c in cases:
  def ev(p,n): return [Evidence(p+str(i),"fact","local_import","fixture://x","x","d",1,1) for i in range(n)]
  async def q(x): return ev("q",c["quick"])
  async def d(x): return ev("d",1 if c["id"] in ("deep","conflict") else 0)
  route,_,_=await AdaptiveResearchRouter(quick_search=q,deep_research=d).run(c["id"],internal=ev("i",c["internal"]),conflict=c["id"]=="conflict"); rows.append({"id":c["id"],"expected":c["expected"],"actual":route,"passed":route==c["expected"]})
 return {"passed":sum(r["passed"] for r in rows),"total":len(rows),"results":rows}
if __name__=="__main__": print(json.dumps(asyncio.run(evaluate()),indent=2))
