"""Fixed FTS retrieval regression set; not report-quality or upstream evaluation."""

import argparse
import asyncio
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from deepresearch_kb.knowledge import KnowledgeStore


def grade(expected, actual):
    expected, actual = set(map(tuple, expected)), set(map(tuple, actual))
    return {"passed": actual == expected,
            "recall": len(actual & expected) / len(expected) if expected else None,
            "precision": len(actual & expected) / len(actual) if actual else None}


async def evaluate(cases_path=None):
    path = Path(cases_path) if cases_path else Path(__file__).with_name("cases.json")
    raw = path.read_bytes()
    dataset = json.loads(raw)
    with tempfile.TemporaryDirectory(prefix="kb-eval-") as directory:
        root = Path(directory)

        async def loader(file):
            return [{"raw_content": file.read_text(encoding="utf-8"), "url": file.name}]

        store = KnowledgeStore(root / "kb.sqlite", loader=loader)
        kbs = {}
        for document in dataset["documents"]:
            name = document["kb"]
            if name not in kbs:
                kbs[name] = store.create_knowledge_base(name).id
            source = root / "input.txt"
            source.write_text(document["text"], encoding="utf-8")
            await store.ingest(kbs[name], source, logical_path=document["path"],
                               source_uri=f"fixture://{name}/{document['path']}")
        # Exercise persistence, not just the original object.
        store = KnowledgeStore(root / "kb.sqlite", loader=loader)
        results = []
        for case in dataset["cases"]:
            evidence = store.retrieve([kbs[case["kb"]]], case["query"], limit=5)
            actual = [[item.logical_path, item.version] for item in evidence]
            results.append({"id": case["id"], "query": case["query"],
                            "expected": case["expected"], "actual": actual,
                            **grade(case["expected"], actual)})
    return {"evaluation": "fixed-retrieval-regression-v1", "dataset_sha256": hashlib.sha256(raw).hexdigest(),
            "passed": sum(item["passed"] for item in results), "total": len(results), "results": results,
            "scope": "Real SQLite FTS; synthetic text loader; no LLM/search/provider; no report scores"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/evals/retrieval.json")
    args = parser.parse_args()
    result = asyncio.run(evaluate())
    result["git_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    result["worktree_dirty"] = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] == result["total"] else 1)


if __name__ == "__main__":
    main()
