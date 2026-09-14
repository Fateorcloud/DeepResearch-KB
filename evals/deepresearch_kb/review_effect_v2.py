"""Manual review checklist for v2 reports; does not mutate gold labels."""
import json, re
from pathlib import Path

def review(root):
    root=Path(root); data=json.loads((root/"dataset.json").read_text()); rows=[]
    for case in data["cases"]:
        for arm in ("fixed_hybrid","adaptive"):
            report=(root/case["id"]/arm/"report.md").read_text()
            rows.append({"id":case["id"],"arm":arm,"report_has_text":bool(report.strip()),
                "citation_links":re.findall(r"\]\(([^)]+)\)",report),
                "gold_status":"needs_review" if case["id"]=="holdout_negation" else "frozen",
                "semantic_answer_review":"manual_read_required"})
    return {"protocol":"manual checklist; no automatic correctness score","rows":rows}
if __name__=="__main__": print(json.dumps(review("data/evals/effect-v2-reports-1"),ensure_ascii=False,indent=2))
