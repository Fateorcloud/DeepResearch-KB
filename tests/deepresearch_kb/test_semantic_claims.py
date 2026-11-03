"""No model downloads or LLM/network calls: embeddings and verdicts are injected."""

import asyncio
import json
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from deepresearch_kb.adaptive import AdaptiveResearchRouter
from deepresearch_kb.engine import ResearchEngine
from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.models import Evidence
from deepresearch_kb.semantic_claims import (
    SemanticClaimReviewer, SemanticConfig, evidence_sentences, rank_candidates)
from deepresearch_kb.sufficiency import EvidenceRequirement, _claim_supported, assess_requirements


class FakeEmbeddings:
    def queries(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def passages(self, texts):
        return [[1.0, 0.0] for _ in texts]


def evidence(text="可以用协程编写异步处理函数。", **changes):
    item = Evidence("e", text, "local_import", "file:///e", "e.md", "doc", 1, 1, status="active")
    return replace(item, **changes)


def reviewer(result="supported", citation_ids=None):
    llm = AsyncMock(return_value=json.dumps({
        "result": result, "citation_ids": ["e:0"] if citation_ids is None else citation_ids}))
    return SemanticClaimReviewer(embeddings=FakeEmbeddings(), reviewer=llm), llm


def assess(review, req=None, items=None):
    return asyncio.run(review.assess(req or EvidenceRequirement("r", ("支持异步函数",)),
                                    [evidence()] if items is None else items))


@pytest.mark.parametrize("negation", ["不", "不是", "并非", "非", "未", "没有", "无", "不能", "不支持"])
def test_chinese_adjacent_negation_rejects_lexical_support(negation):
    assert not _claim_supported("支持 OAuth2", negation + "支持 OAuth2")
    assert not _claim_supported("支持 OAuth2", "不支持 OAuth2")
    assert _claim_supported("支持 OAuth2", "系统支持 OAuth2")


def test_english_negation_is_preserved():
    assert not _claim_supported("supports OAuth2", "It is false that supports OAuth2")


def test_paraphrase_with_valid_citation_satisfies_claim():
    review, llm = reviewer()
    assert not _claim_supported("支持异步函数", evidence().text)
    result = assess(review)
    assert result["satisfied"]
    record = result["claims"][0]
    assert record["stage"] == "semantic"
    assert record["citation_ids"] == ["e:0"]
    assert record["candidates"][0]["similarity"] == 1.0
    llm.assert_awaited_once()


def test_lexical_success_skips_embeddings_and_llm():
    class UnusedEmbeddings:
        def queries(self, texts):
            raise AssertionError("lexical support must skip embeddings")

    llm = AsyncMock()
    review = SemanticClaimReviewer(embeddings=UnusedEmbeddings(), reviewer=llm)
    result = assess(review, items=[evidence("支持异步函数。")])
    assert result["satisfied"]
    assert result["claims"][0]["stage"] == "lexical"
    llm.assert_not_awaited()


@pytest.mark.parametrize("output", [
    '{"result":"supported","citation_ids":["invented:0"]}',
    '{"result":"supported","citation_ids":[]}',
    '{"result":"supported","citation_ids":["e:0","invented:0"]}',
    '{"result":"supported","citation_ids":"e:0"}',
    '{"result":"supported"}', 'not json', '[]',
    '{"result":"unknown","citation_ids":[]}',
])
def test_invalid_or_ungrounded_verdict_is_unknown(output):
    review = SemanticClaimReviewer(embeddings=FakeEmbeddings(), reviewer=AsyncMock(return_value=output))
    result = assess(review)
    assert not result["satisfied"]
    assert result["claims"][0]["result"] == "unknown"
    assert result["claims"][0]["citation_ids"] == []


def test_contradicted_enters_conflict_route():
    review, _ = reviewer("contradicted")
    quick, deep = AsyncMock(return_value=[]), AsyncMock(return_value=[])
    router = AdaptiveResearchRouter(quick_search=quick, deep_research=deep,
        requirements=[EvidenceRequirement("r", ("支持异步函数",))], claim_reviewer=review)
    route, _, decisions = asyncio.run(router.run("q", internal=[evidence("禁止使用异步处理函数。")]))
    assert route == "deep"
    assert decisions[0].terminal_status == decisions[-1].terminal_status == "conflict"
    quick.assert_not_awaited()
    deep.assert_awaited_once()


def test_high_similarity_not_found_never_supports_claim():
    review, _ = reviewer("not_found", [])
    result = assess(review)
    assert result["claims"][0]["candidates"][0]["similarity"] == 1.0
    assert result["claims"][0]["result"] == "not_found"
    assert not result["satisfied"]


@pytest.mark.parametrize("requirement,items", [
    (EvidenceRequirement("r", ("支持异步函数",), ("external_web",)), [evidence()]),
    (EvidenceRequirement("r", ("支持异步函数",), require_current_version=True), [evidence(status="superseded")]),
    (EvidenceRequirement("r", ("支持异步函数",), minimum_distinct_sources=2), [evidence(), evidence(chunk_id="other")]),
    (EvidenceRequirement("r", ("支持异步函数",)), [evidence(source_uri="")]),
])
def test_semantic_support_cannot_waive_hard_constraints(requirement, items):
    review, _ = reviewer()
    result = assess(review, requirement, items)
    assert result["claims"][0]["result"] == "supported"
    assert not result["satisfied"]


def test_unrelated_source_cannot_supply_semantic_provenance():
    review, _ = reviewer()
    req = EvidenceRequirement("r", ("支持异步函数",), ("external_web",))
    result = assess(review, req, [evidence(), evidence("其他主题。", chunk_id="other", source_type="external_web")])
    assert not result["satisfied"]  # The LLM cited only the local sentence.


@pytest.mark.parametrize("error", [ModuleNotFoundError, FileNotFoundError])
def test_unavailable_semantics_preserves_lexical_result_and_trace(tmp_path, error):
    class MissingEmbeddings:
        def queries(self, texts):
            raise error("credential-like text must never reach trace")

    review = SemanticClaimReviewer(embeddings=MissingEmbeddings(), reviewer=AsyncMock())
    req = EvidenceRequirement("r", ("支持异步函数",))
    items = [evidence()]
    baseline = assess_requirements([req], items)[0]
    result = assess(review, req, items)
    assert result["satisfied"] == baseline.satisfied
    assert result["status"] == result["claims"][0]["semantic_status"] == "semantic_unavailable"
    assert "credential-like" not in json.dumps(result)

    store = KnowledgeStore(tmp_path / "kb.sqlite")
    engine = ResearchEngine(store=store, quick_search=AsyncMock(return_value=items),
        deep_research=AsyncMock(return_value=[]), claim_reviewer=review,
        researcher_factory=lambda q: type("Writer", (), {"write_report": AsyncMock(return_value="report")})())
    output = tmp_path / "run"
    asyncio.run(engine.run("q", knowledge_base_ids=[], requirements=req,
                          subquestions=["q"], output_dir=output))
    trace = json.loads((output / "trace.json").read_text())
    assert "semantic_unavailable" in json.dumps(trace)
    assert trace[0]["decisions"][-1]["terminal_status"] == "insufficient"


@pytest.mark.parametrize("stage", ["internal", "quick", "deep"])
def test_semantic_support_is_reviewed_after_each_retrieval_stage(stage):
    review, llm = reviewer()
    quick = AsyncMock(return_value=[evidence()] if stage == "quick" else [])
    deep = AsyncMock(return_value=[evidence()] if stage == "deep" else [])
    router = AdaptiveResearchRouter(quick_search=quick, deep_research=deep,
        claim_reviewer=review, requirements=[EvidenceRequirement("r", ("支持异步函数",))])
    route, _, decisions = asyncio.run(router.run("q", internal=[evidence()] if stage == "internal" else []))
    assert route == {"internal": "stop", "quick": "quick", "deep": "deep"}[stage]
    assert decisions[-1].terminal_status == ("sufficient" if stage == "deep" else None)
    assert router.claim_reviews[-1]["requirements"][0]["satisfied"]
    llm.assert_awaited_once()


def test_provider_initialization_failure_disables_semantics(monkeypatch):
    def unavailable(usage):
        raise ValueError("secret-config")

    monkeypatch.setattr("deepresearch_kb.semantic_claims.configured_claim_reviewer", unavailable)
    result = assess(SemanticClaimReviewer(embeddings=FakeEmbeddings()))
    assert result["status"] == "semantic_unavailable"
    assert not result["satisfied"]
    assert "secret-config" not in json.dumps(result)


@pytest.mark.parametrize("checker_status", ["not_applicable", "unknown"])
def test_semantic_conflict_survives_conflict_checker(checker_status):
    review, _ = reviewer("contradicted")
    checker = AsyncMock()
    checker.check.return_value = {"status": checker_status, "pairs": []}
    router = AdaptiveResearchRouter(quick_search=AsyncMock(return_value=[]),
        deep_research=AsyncMock(return_value=[]), claim_reviewer=review,
        requirements=[EvidenceRequirement("r", ("支持异步函数",))])
    _, _, decisions = asyncio.run(router.run("q", internal=[evidence()], conflict_checker=checker))
    assert decisions[-1].terminal_status == "conflict"


def test_sentence_split_and_top_k_threshold():
    items = [evidence("中文。第二句！Third sentence. Fourth? Value 1.5 is valid.")]
    sentences = evidence_sentences(items)
    assert len(sentences) == 5
    assert "1.5" in sentences[-1]["text"]
    ranked = rank_candidates(["claim"], sentences, FakeEmbeddings(), SemanticConfig(top_k=2, min_similarity=.9))
    assert [s["sentence_id"] for s in ranked[0]] == ["e:0", "e:1"]


def test_below_threshold_skips_llm():
    class DistantEmbeddings(FakeEmbeddings):
        def passages(self, texts):
            return [[0.0, 1.0] for _ in texts]

    llm = AsyncMock()
    review = SemanticClaimReviewer(embeddings=DistantEmbeddings(), reviewer=llm,
                                   config=SemanticConfig(min_similarity=.9))
    result = assess(review)
    assert not result["satisfied"]
    assert result["claims"][0]["candidates"] == []
    llm.assert_not_awaited()
