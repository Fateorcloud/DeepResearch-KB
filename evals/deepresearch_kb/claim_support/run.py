"""Calibrate sentence recall on dev, then evaluate three fixed support methods."""

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from deepresearch_kb.models import Evidence
from deepresearch_kb.semantic_claims import (
    EMBED_MODEL, FastEmbedEmbeddings, SemanticClaimReviewer, SemanticConfig,
    configured_claim_reviewer, evidence_sentences, rank_candidates)
from deepresearch_kb.sufficiency import EvidenceRequirement, _claim_supported
from ..retrieval_v2.fetch_corpus import DEFAULT_CORPUS, MANIFEST

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases.json"
TYPES = {"literal", "paraphrase", "negation", "related"}


def split_of(case_id):
    return "test" if int(hashlib.sha256(case_id.encode()).hexdigest(), 16) % 5 < 2 else "dev"


def load_cases(corpus=DEFAULT_CORPUS):
    data = json.loads(CASES.read_text())
    manifest = json.loads(MANIFEST.read_text())
    seen = set()
    for case in data["cases"]:
        if case["id"] in seen or case["type"] not in TYPES or not case["rationale"].strip():
            raise ValueError("invalid case metadata")
        seen.add(case["id"])
        path = "v2/" + case["source"]["path"]
        raw = (corpus / path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["files"][path]:
            raise ValueError("corpus digest mismatch")
        if case["evidence"] not in raw.decode():
            raise ValueError("evidence is not an exact corpus sentence")
        expected = "contradicted" if case["type"] == "negation" else "not_found" if case["type"] == "related" else "supported"
        if case["label"] != expected:
            raise ValueError("unexpected label")
    return data["cases"]


def item_for(case):
    return Evidence(case["id"], case["evidence"], "local_import", "file:///" + case["source"]["path"],
                    case["source"]["path"], case["source"]["path"], 1, 1.0, status="active")


class CachedEmbeddings:
    def __init__(self, base, cases):
        queries = list(dict.fromkeys(c["claim"] for c in cases))
        texts = list(dict.fromkeys(s["text"] for c in cases for s in evidence_sentences([item_for(c)])))
        self.q = dict(zip(queries, base.queries(queries)))
        self.p = dict(zip(texts, base.passages(texts)))

    def queries(self, texts):
        return [self.q[t] for t in texts]

    def passages(self, texts):
        return [self.p[t] for t in texts]


def score_cases(cases, embeddings):
    return {c["id"]: rank_candidates([c["claim"]], evidence_sentences([item_for(c)]),
                                     embeddings, SemanticConfig(top_k=1, min_similarity=-1))[0][0]["similarity"]
            for c in cases}


def calibrate(cases, scores):
    """Highest grid threshold retaining >=95% of supported dev candidates."""
    if not cases or any(split_of(c["id"]) != "dev" for c in cases):
        raise ValueError("calibration accepts dev cases only")
    supported = [c for c in cases if c["label"] == "supported"]
    trials = []
    for step in range(30, 96):
        threshold = step / 100
        recall = sum(scores[c["id"]] >= threshold for c in supported) / len(supported)
        trials.append({"threshold": threshold, "supported_candidate_recall": recall})
    eligible = [t for t in trials if t["supported_candidate_recall"] >= .95]
    if not eligible:
        raise ValueError("grid cannot achieve target dev candidate recall")
    return {"threshold": eligible[-1]["threshold"], "objective": "highest threshold with supported dev candidate recall >= 0.95",
            "dev_ids": [c["id"] for c in cases], "trials": trials}


def metrics(cases, predictions):
    para = [c for c in cases if c["type"] == "paraphrase"]
    negative = [c for c in cases if c["type"] == "negation"]
    return {"paraphrase_support_recall": sum(predictions[c["id"]] == "supported" for c in para) / len(para),
            "negation_false_support_rate": sum(predictions[c["id"]] == "supported" for c in negative) / len(negative),
            "accuracy": sum(predictions[c["id"]] == c["label"] for c in cases) / len(cases),
            "counts": {"total": len(cases), "paraphrase": len(para), "negation": len(negative)},
            "prediction_counts": dict(Counter(predictions.values()))}


async def evaluate(cases, embeddings, scores, threshold, llm):
    methods = {"lexical": {}, "vector_only": {}}
    details = {}
    for case in cases:
        key = case["id"]
        methods["lexical"][key] = "supported" if _claim_supported(case["claim"], case["evidence"]) else "not_found"
        methods["vector_only"][key] = "supported" if scores[key] >= threshold else "not_found"
    llm_status = {"status": "disabled"}
    if llm != "off":
        try:
            from gpt_researcher.config import Config
            cfg = Config()
            call = configured_claim_reviewer()
            llm_status = {"status": "ran", "provider": cfg.smart_llm_provider, "model": cfg.smart_llm_model}
        except Exception as exc:
            llm_status = {"status": "unavailable", "error_type": type(exc).__name__}
        else:
            gate = asyncio.Semaphore(4)
            methods["lexical_vector_llm"] = {}

            async def one(case):
                async with gate:
                    review = SemanticClaimReviewer(embeddings=embeddings, reviewer=call,
                        config=SemanticConfig(min_similarity=threshold))
                    result = await review.assess(EvidenceRequirement(case["id"], (case["claim"],)), [item_for(case)])
                    details[case["id"]] = result["claims"][0]
                    methods["lexical_vector_llm"][case["id"]] = result["claims"][0]["result"]

            await asyncio.gather(*(one(c) for c in cases))
            llm_status["reviewed_claims"] = sum(d["stage"] == "semantic" and bool(d["candidates"]) for d in details.values())
            llm_status["unknown_claims"] = sum(d["result"] == "unknown" for d in details.values())
    return {"llm": llm_status,
            "metrics": {name: metrics(cases, predictions) for name, predictions in methods.items()},
            "predictions": methods, "claim_reviews": details, "cosine_scores": scores}


def main():
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--llm", choices=["auto", "off"], default="auto")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.calibrate and args.split != "dev":
        parser.error("threshold calibration is restricted to dev")
    load_dotenv()
    cases = [c for c in load_cases(args.corpus) if split_of(c["id"]) == args.split]
    embeddings = CachedEmbeddings(FastEmbedEmbeddings(), cases)
    scores = score_cases(cases, embeddings)
    calibration = calibrate(cases, scores) if args.calibrate else None
    threshold = calibration["threshold"] if calibration else SemanticConfig().min_similarity
    result = asyncio.run(evaluate(cases, embeddings, scores, threshold, args.llm))
    result.update(split=args.split, threshold=threshold, top_k=5, embedding_model=EMBED_MODEL,
                  fastembed_version=importlib.metadata.version("fastembed"),
                  dataset_sha256=hashlib.sha256(CASES.read_bytes()).hexdigest(),
                  split_rule="sha256(id) % 5 < 2 => test; otherwise dev",
                  case_ids=[c["id"] for c in cases], types=dict(Counter(c["type"] for c in cases)),
                  timestamp_utc=datetime.now(timezone.utc).isoformat())
    if calibration:
        (HERE / "calibration.json").write_text(json.dumps(calibration, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    target = args.output or HERE / f"results_{args.split}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"split": args.split, "threshold": threshold, "llm": result["llm"], "metrics": result["metrics"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
