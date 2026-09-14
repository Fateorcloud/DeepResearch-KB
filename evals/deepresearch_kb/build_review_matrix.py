"""Build a review matrix for paired reports without assigning semantic scores."""
import json
from pathlib import Path


def build(root="data/evals/effect-v2-reports-1", output="data/evals/effect-v2-reports-1/review-matrix.json"):
    root = Path(root)
    dataset = json.loads((root / "dataset.json").read_text(encoding="utf-8"))
    rows = []
    for case in dataset["cases"]:
        for arm in ("fixed_hybrid", "adaptive"):
            folder = root / case["id"] / arm
            report = (folder / "report.md").read_text(encoding="utf-8")
            rows.append({
                "id": case["id"], "split": case["split"], "arm": arm,
                "question": case["question"], "required_claims": case["required_claims"],
                "answerable_gold": case["answerable"], "expected_route": case["expected_route"],
                "report_path": str((folder / "report.md").as_posix()),
                "review": {"claim_status": "unreviewed", "citation_status": "unreviewed",
                           "stale_status": "unreviewed", "notes": ""},
                "report_preview": report[:500],
            })
    payload = {"protocol": "human review matrix; blank labels are intentional",
               "scoring": "Reviewer must mark supported/unsupported/uncertain per claim and cite exact report text",
               "rows": rows}
    path = Path(output); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    payload = build()
    print(json.dumps({"rows": len(payload["rows"]), "status": "unreviewed"}, ensure_ascii=False))
