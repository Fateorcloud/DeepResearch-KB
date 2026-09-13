"""Explicit real-model conflict evaluation; one call per fixed pair."""

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path

from dotenv import load_dotenv

from deepresearch_kb.conflicts import configured_conflict_checker
from deepresearch_kb.metrics import UsageCollector
from deepresearch_kb.models import Evidence


async def evaluate(output):
    raw = Path(__file__).with_name("conflict_cases.json").read_bytes()
    dataset = json.loads(raw)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError("use a new output path to preserve prior results")
    usage = UsageCollector()
    checker = configured_conflict_checker(usage)
    result = {"dataset_sha256": hashlib.sha256(raw).hexdigest(), "results": [], "scope": dataset["scope"]}
    for case in dataset["cases"]:
        left = Evidence(case["id"] + "-i", case["left"], "local_import", "fixture://internal", "internal", "d", 1, 0)
        right = Evidence(case["id"] + "-e", case["right"], "external_web", "https://example.test/fixture", "external", "", 1, 0)
        start = time.perf_counter()
        review = await checker.check([left, right])
        actual = review["pairs"][0]["verdict"] if review["status"] == "reviewed" else "unknown"
        result["results"].append({"id": case["id"], "expected": case["expected"], "actual": actual,
            "valid_review": review["status"] == "reviewed",
            "passed": actual == case["expected"] and review["status"] == "reviewed",
            "latency_seconds": time.perf_counter() - start, "review": review})
        result["usage"] = usage.summary()
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{case['id']}: {actual} ({review['status']})", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    load_dotenv()
    result = asyncio.run(evaluate(args.output))
    raise SystemExit(0 if all(row["passed"] for row in result["results"]) else 1)
