"""Versioned Chinese retrieval benchmark over the pinned FastAPI zh docs.

Retrieval only: no LLM, web search or report scoring. Labels are answer spans
rather than chunk ids, so they survive chunking changes: a returned chunk is
relevant when it comes from the gold page and contains the span after
normalisation. v1 pages are ingested before v2, so changed pages carry a
superseded version that a retriever must not return.
"""

import argparse
import asyncio
import hashlib
import json
import re
import statistics
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from deepresearch_kb.knowledge import KnowledgeStore

from .fetch_corpus import DEFAULT_CORPUS, MANIFEST, SNAPSHOTS, check
from .retrievers import RETRIEVERS, Workbench

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases.json"
TYPES = ("fact", "paraphrase", "version", "no_answer")
SNAPSHOT_TIMES = {"v1": datetime(2023, 7, 7, tzinfo=timezone.utc),
                  "v2": datetime(2026, 10, 31, tzinfo=timezone.utc)}
KS = (1, 5, 10)
_STRIP = re.compile(r"[\s`*]")


def normalize(text):
    return _STRIP.sub("", text)


def split_of(key):
    """Deterministic dev/test split by gold page, so one page never spans both."""
    return "test" if int(hashlib.sha256(key.encode()).hexdigest(), 16) % 5 < 2 else "dev"


def _case_split(case):
    return split_of(case["gold"][0]["path"] if case["gold"] else case["id"])


def load_cases(path=CASES):
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    seen = set()
    for case in data["cases"]:
        if case["id"] in seen:
            raise ValueError(f"duplicate case id {case['id']}")
        seen.add(case["id"])
        if case["type"] not in TYPES:
            raise ValueError(f"{case['id']}: unknown type {case['type']}")
        if (case["type"] == "no_answer") == bool(case["gold"]):
            raise ValueError(f"{case['id']}: gold must be empty exactly for no_answer")
        if any(not gold.get("path") or not normalize(gold.get("span", "")) for gold in case["gold"]):
            raise ValueError(f"{case['id']}: gold needs path and span")
    return data, hashlib.sha256(raw).hexdigest()


def validate_labels(cases, corpus):
    """Every gold span must occur in the current (v2) page it points to."""
    problems = []
    for case in cases:
        for gold in case["gold"]:
            page = Path(corpus) / "v2" / gold["path"]
            if not page.is_file():
                problems.append(f"{case['id']}: missing page {gold['path']}")
            elif normalize(gold["span"]) not in normalize(page.read_text(encoding="utf-8")):
                problems.append(f"{case['id']}: span not found in {gold['path']}")
    return problems


def grade_case(case, evidence, latest):
    """Grade ranked ``(path, version, text)`` evidence for one case."""
    result = {"returned": len(evidence),
              "stale": sum(1 for path, version, _ in evidence if version < latest.get(path, version))}
    if case["type"] == "no_answer":
        return result
    golds = [(gold["path"], normalize(gold["span"])) for gold in case["gold"]]
    gold_paths = {path for path, _ in golds}
    doc_rank = span_rank = None
    for rank, (path, _version, text) in enumerate(evidence, 1):
        if doc_rank is None and path in gold_paths:
            doc_rank = rank
        if span_rank is None and any(path == p and span in normalize(text) for p, span in golds):
            span_rank = rank
    result.update(doc_rank=doc_rank, span_rank=span_rank)
    return result


def _mean(values):
    values = list(values)
    return round(sum(values) / len(values), 4) if values else None


def summarize(rows):
    answerable = [row for row in rows if row["type"] != "no_answer"]
    no_answer = [row for row in rows if row["type"] == "no_answer"]
    summary = {"cases": len(rows), "answerable": len(answerable)}
    for k in KS:
        for key in ("doc", "span"):
            summary[f"{key}_recall@{k}"] = _mean(
                row[f"{key}_rank"] is not None and row[f"{key}_rank"] <= k for row in answerable)
    summary["span_mrr@10"] = _mean(
        1 / row["span_rank"] if row["span_rank"] and row["span_rank"] <= 10 else 0 for row in answerable)
    summary["empty_rate"] = _mean(row["returned"] == 0 for row in answerable)
    summary["no_answer_nonempty_rate"] = _mean(row["returned"] > 0 for row in no_answer)
    returned = sum(row["returned"] for row in rows)
    summary["stale_rate"] = round(sum(row["stale"] for row in rows) / returned, 4) if returned else None
    latencies = sorted(row["latency_ms"] for row in rows)
    if latencies:
        summary["latency_ms_p50"] = round(statistics.median(latencies), 2)
        summary["latency_ms_p95"] = latencies[int(0.95 * (len(latencies) - 1))]
    return summary


async def build_store(corpus, root):
    async def loader(file):
        return [{"raw_content": file.read_text(encoding="utf-8"), "url": file.name}]

    store = KnowledgeStore(Path(root) / "kb.sqlite", loader=loader)
    kb = store.create_knowledge_base("fastapi-zh").id
    skipped = []
    for label in ("v1", "v2"):
        base = Path(corpus) / label
        for page in sorted(base.rglob("*.md")):
            relative = page.relative_to(base).as_posix()
            if not page.read_text(encoding="utf-8").strip():
                skipped.append(f"{label}/{relative}")
                continue
            await store.ingest(kb, page, logical_path=relative, updated_at=SNAPSHOT_TIMES[label],
                               source_uri=f"fastapi-zh://{label}/{relative}")
    latest = {doc_path: store.list_versions(kb, doc_path)[-1].version
              for doc_path in sorted({p.relative_to(Path(corpus) / label).as_posix()
                                      for label in ("v1", "v2")
                                      for p in (Path(corpus) / label).rglob("*.md")})
              if store.list_versions(kb, doc_path)}
    return store, kb, latest, skipped



async def evaluate(corpus=DEFAULT_CORPUS, cases_path=CASES, retrievers=("fts5",), limit=10,
                   split="all", cache_dir=Path("data/evals/retrieval_v2/cache")):
    data, digest = load_cases(cases_path)
    problems = validate_labels(data["cases"], corpus)
    if problems:
        raise ValueError("invalid labels:\n" + "\n".join(problems))
    results = {}
    with tempfile.TemporaryDirectory(prefix="kb-retrieval-v2-") as directory:
        store, kb, latest, skipped = await build_store(corpus, directory)
        bench = Workbench(store, kb, cache_dir)
        cases = [c for c in data["cases"]
                 if split == "all" or _case_split(c) == split]
        for name in retrievers:
            search = RETRIEVERS[name](bench)
            rows = []
            for case in cases:
                started = time.perf_counter()
                evidence = search(case["query"], limit)
                elapsed = round((time.perf_counter() - started) * 1000, 2)
                ranked = [(item.logical_path, item.version, item.text) for item in evidence]
                rows.append({"id": case["id"], "type": case["type"], "split": _case_split(case),
                             "latency_ms": elapsed, **grade_case(case, ranked, latest),
                             "top3": [[path, version] for path, version, _ in ranked[:3]]})
            results[name] = {
                "overall": summarize(rows),
                "by_split": {s: summarize([r for r in rows if r["split"] == s]) for s in ("dev", "test")},
                "by_type": {t: summarize([r for r in rows if r["type"] == t]) for t in TYPES},
                "rows": rows,
            }
    return {"evaluation": data["name"], "dataset_sha256": digest, "corpus_snapshots": SNAPSHOTS,
            "documents": len(latest), "superseded_documents": sum(v > 1 for v in latest.values()),
            "skipped_empty_pages": skipped, "limit": limit, "split": split,
            "active_chunks": len(bench.chunks), "results": results,
            "scope": "Retrieval only; FastAPI zh docs; no LLM, web search or report scores."}


def _print_table(report):
    keys = ("span_recall@1", "span_recall@5", "span_recall@10", "doc_recall@5", "span_mrr@10",
            "empty_rate", "stale_rate", "no_answer_nonempty_rate", "latency_ms_p50")
    print("retriever  scope       " + "  ".join(f"{k:>14}" for k in keys))
    for name, result in report["results"].items():
        scopes = {"all": result["overall"], **result["by_type"]}
        for scope, summary in scopes.items():
            cells = ["-" if summary.get(k) is None else f"{summary[k]:.3f}" for k in keys]
            print(f"{name:<10} {scope:<11} " + "  ".join(f"{c:>14}" for c in cells))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--retriever", action="append", choices=sorted(RETRIEVERS) + ["all"])
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev",
                        help="compare candidates on dev; run test once after choosing")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    problems = check(args.corpus, json.loads(MANIFEST.read_text(encoding="utf-8")))
    if problems:
        raise SystemExit("corpus differs from manifest; run fetch_corpus first:\n" + "\n".join(problems[:10]))
    names = tuple(args.retriever or ("fts5",))
    if "all" in names:
        names = tuple(RETRIEVERS)
    report = asyncio.run(evaluate(args.corpus, retrievers=names, split=args.split))
    report["git_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    report["worktree_dirty"] = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    args.output = args.output or Path(f"data/evals/retrieval_v2/results-{args.split}.json")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    _print_table(report)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
