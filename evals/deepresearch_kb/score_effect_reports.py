"""Conservative report diagnostics over frozen v2 artifacts; not an entailment judge."""
import json, re
from pathlib import Path

def score(root="data/evals/effect-v2-reports-1"):
    root=Path(root); data=json.loads((root/"dataset.json").read_text()); out=[]
    for case in data["cases"]:
        for arm in ("fixed_hybrid","adaptive"):
            folder=root/case["id"]/arm; report=(folder/"report.md").read_text(); sources=json.loads((folder/"sources.json").read_text())
            allowed={s.get("source_uri","") for s in sources}
            for s in sources:
                if s.get("source_type") != "external_web" and s.get("document_id"):
                    allowed.add(f"kb://{s['document_id']}/versions/{s.get('version', 1)}/chunks/{s.get('chunk_id', '')}")
            links=set(re.findall(r"\]\(([^)]+)\)",report))
            mentions={claim: bool(re.search(re.escape(claim),report,re.I)) for claim in case["required_claims"]}
            refusal=bool(re.search(r"cannot|unavailable|not determin|insufficient|missing|conflict",report,re.I))
            out.append({"id":case["id"],"arm":arm,"target_claim_mentions":mentions,"all_target_mentions":all(mentions.values()),
                        "valid_citations":len(links & allowed),"invalid_citations":sorted(links-allowed),
                        "conservative_refusal":refusal,"gold_answerable":case["answerable"],
                        "diagnostic_note":"mentions/refusal/URI membership only; manual semantic review required"})
    return {"protocol":"frozen v2 report diagnostics","results":out,
            "scope":"No LLM judge; no claim entailment or quality superiority inference"}

if __name__=="__main__": print(json.dumps(score(),ensure_ascii=False,indent=2))
