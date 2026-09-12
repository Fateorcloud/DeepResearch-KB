"""Summarize explicitly reviewed target facts and provider metrics."""

import argparse
import json
from pathlib import Path


def summarize(directory):
    root = Path(directory)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    review = json.loads((root / "review.json").read_text(encoding="utf-8"))
    dataset = json.loads((root / "dataset.json").read_text(encoding="utf-8"))
    facts = {c["id"]: {f["id"] for f in c["facts"]} for c in dataset["cases"]}
    rows = {(r["case_id"], r["arm"]): r for r in review["rows"]}
    summary = {}
    for record in manifest["results"]:
        key = (record["case_id"], record["arm"])
        r = rows[key]
        assessed = r["correct_supported"] + r["unavailable"] + r["incorrect"]
        if set(assessed) != facts[record["case_id"]] or len(assessed) != len(set(assessed)):
            raise ValueError("review must assess every gold fact exactly once")
        value = summary.setdefault(record["arm"], {
            "reports": 0, "completed": 0, "supported_facts": 0, "target_facts": 0,
            "unavailable": 0, "incorrect": 0, "stale_current_errors": 0,
            "input_tokens": 0, "output_tokens": 0, "latency_seconds": 0.0,
            "llm_calls": 0, "replay_retriever_calls": 0, "actual_cost_usd": None})
        value["reports"] += 1
        value["completed"] += record["status"] == "completed"
        value["supported_facts"] += len(r["correct_supported"])
        value["target_facts"] += len(assessed)
        value["unavailable"] += len(r["unavailable"])
        value["incorrect"] += len(r["incorrect"])
        value["stale_current_errors"] += r["stale_current_errors"]
        for field in ("input_tokens", "output_tokens"):
            amount = (record["llm_tokens"] or {}).get(field)
            value[field] = (value[field] + amount if value[field] is not None and amount is not None else None)
        value["latency_seconds"] += record["latency_seconds"]
        value["llm_calls"] += record["llm_calls_completed"]
        value["replay_retriever_calls"] += record["retriever_calls"]
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default=str(Path(__file__).parent / "results/phase1-v1"))
    args = parser.parse_args()
    print(json.dumps(summarize(args.directory), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
