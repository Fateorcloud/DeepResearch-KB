import asyncio
import json
import pytest
from pathlib import Path
from deepresearch_kb.knowledge import KnowledgeStore
from datetime import datetime, timezone
from deepresearch_kb.engine import ResearchEngine
from deepresearch_kb.models import Evidence
from deepresearch_kb.research import render_evidence_context


class _Researcher:
    @property
    def research_conductor(self):
        return self

    async def plan_research(self, query):
        assert query == "project"
        return ["internal", "quick", "deep"]

    async def write_report(self, *, ext_context):
        return "REPORT\n" + ext_context


def ev(text, uri="kb://doc"):
    return Evidence(text, text, "local_import", uri, "doc.md", "doc", 1, 1.0,
                    "kb", effective_at="2026-01-01T00:00:00+00:00", status="active")


def test_unified_engine_runs_stop_quick_and_deep(tmp_path):
    progress_events = []
    async def loader(path):
        return [{"raw_content": path.read_text(), "url": path.name}]
    store = KnowledgeStore(Path(tmp_path) / "kb.sqlite", loader=loader)
    kb = store.create_knowledge_base("integration")
    source = Path(tmp_path) / "internal.md"
    source.write_text("internal claim")
    asyncio.run(store.ingest(kb.id, source, logical_path="internal.md"))
    async def quick(q):
        return [] if q == "deep" else [ev("quick claim", "https://quick")]
    async def deep(q):
        return [ev("deep claim", "https://deep")]
    engine = ResearchEngine(store=store, quick_search=quick, deep_research=deep,
                            researcher_factory=lambda q: _Researcher())
    from deepresearch_kb.sufficiency import EvidenceRequirement
    reqs = [EvidenceRequirement("r1", ("internal claim",)),
            EvidenceRequirement("r2", ("quick claim",)),
            EvidenceRequirement("r3", ("deep claim",))]
    result = asyncio.run(engine.run("project", knowledge_base_ids=[kb.id],
                              requirements=reqs,
                              output_dir=tmp_path / "run",
                              progress=progress_events.append))
    assert [t["final_route"] for t in result["trace"]] == ["stop", "quick", "deep"]
    assert result["metrics"]["quick_calls"] == 2
    assert result["metrics"]["deep_calls"] == 1
    assert (tmp_path / "run" / "sources.json").read_text()
    assert "deep claim" in result["report"]
    assert result["metrics"]["planning_source"] == "upstream_plan_research"
    assert result["trace"][0]["internal_evidence"][0]["status"] == "active"
    saved = json.loads((tmp_path / "run" / "sources.json").read_text())
    assert result["report"] == "REPORT\n" + render_evidence_context([Evidence(**e) for e in saved])
    assert result["trace"][1]["quick_evidence"]
    assert result["trace"][2]["deep_evidence"]
    assert result["trace"][2]["decisions"][-1]["terminal_status"] == "sufficient"
    assert progress_events[0] == {
        "phase": "planning", "progress_percent": 5, "evidence_count": 0}
    assert progress_events[-1]["phase"] == "finalizing"
    assert progress_events[-1]["progress_percent"] == 95
    assert progress_events[-1]["evidence_count"] == 3
    assert {event["phase"] for event in progress_events} >= {
        "planning", "retrieval", "quick_research", "deep_research",
        "sufficiency", "synthesis", "finalizing"}


def test_internal_policy_blocks_external_calls(tmp_path):
    store = KnowledgeStore(tmp_path / "kb.sqlite")
    kb = store.create_knowledge_base("internal")

    async def forbidden(query):
        raise AssertionError("internal policy must not call external research")

    from deepresearch_kb.sufficiency import EvidenceRequirement
    engine = ResearchEngine(store=store, quick_search=forbidden,
                            deep_research=forbidden, researcher_factory=lambda q: _Researcher())
    result = asyncio.run(engine.run("our project", knowledge_base_ids=[kb.id],
        subquestions=["our project"], requirements=[EvidenceRequirement("missing", ("missing fact",))]))
    assert result["metrics"]["quick_calls"] == result["metrics"]["deep_calls"] == 0
    assert result["trace"][0]["policy_blocked_calls"] == ["quick", "deep"]
    assert result["trace"][0]["decisions"][-1]["terminal_status"] == "insufficient"
    assert result["metrics"]["status"] == "incomplete"


def test_language_and_research_depth_are_applied_to_researcher_config(tmp_path):
    store = KnowledgeStore(tmp_path / "settings.sqlite")
    captured = []

    class ConfiguredResearcher(_Researcher):
        def __init__(self):
            from types import SimpleNamespace
            self.cfg = SimpleNamespace(
                language="english", reasoning_effort="low", llm_kwargs={})

    def factory(query):
        researcher = ConfiguredResearcher()
        captured.append(researcher)
        return researcher

    async def quick(query):
        return [Evidence(
            "web", "supported", "external_web", "https://example.org",
            "web", "", 1, 1.0)]

    from deepresearch_kb.sufficiency import EvidenceRequirement
    engine = ResearchEngine(
        store=store, researcher_factory=factory, quick_search=quick)
    asyncio.run(engine.run(
        "external", knowledge_base_ids=[], subquestions=["external"],
        requirements=[EvidenceRequirement("r", ("supported",))],
        output_language="Chinese", research_depth="high"))

    assert captured
    assert captured[0].cfg.language == "Chinese"
    assert captured[0].cfg.reasoning_effort == "high"
    assert captured[0].cfg.max_iterations == 5
    assert captured[0].cfg.max_subtopics == 5
    assert captured[0].cfg.max_search_results_per_query == 8


def test_local_kb_only_requirement_blocks_external_expansion(tmp_path):
    store = KnowledgeStore(tmp_path / "local-only.sqlite")
    kb = store.create_knowledge_base("local-only")
    calls = []

    async def forbidden(query):
        calls.append(query)
        return []

    from deepresearch_kb.sufficiency import EvidenceRequirement
    engine = ResearchEngine(
        store=store, quick_search=forbidden, deep_research=forbidden,
        researcher_factory=lambda q: _Researcher())
    result = asyncio.run(engine.run(
        "general question", knowledge_base_ids=[kb.id],
        subquestions=["general question"],
        requirements=[EvidenceRequirement(
            "local-only", ("missing",), ("local_import",))]))

    assert calls == []
    assert result["metrics"]["quick_calls"] == 0
    assert result["metrics"]["deep_calls"] == 0
    assert result["trace"][0]["source_constraint"] == {
        "internal_allowed": True, "external_allowed": False}
    assert result["trace"][0]["policy_blocked_calls"] == ["quick", "deep"]


def test_usage_is_per_run_and_not_inferred_from_tool_calls(tmp_path):
    from types import SimpleNamespace
    from deepresearch_kb.sufficiency import EvidenceRequirement
    store = KnowledgeStore(tmp_path / "usage.sqlite")
    kb = store.create_knowledge_base("usage")

    class Reporter(_Researcher):
        def __init__(self):
            self.cfg = SimpleNamespace(llm_kwargs={})

        async def write_report(self, *, ext_context):
            collector = self.cfg.llm_kwargs["callbacks"][0]
            collector.on_chat_model_start({}, [])
            collector.on_llm_end(SimpleNamespace(generations=[], llm_output={
                "token_usage": {"prompt_tokens": 12, "completion_tokens": 4}}), run_id="synthetic-response")
            return await super().write_report(ext_context=ext_context)

    async def quick(query):
        return [Evidence("web", "supported fact", "external_web", "https://example.org", "web", "", 1, 0)]

    engine = ResearchEngine(store=store, quick_search=quick,
                            researcher_factory=lambda q: Reporter())
    for _ in range(2):
        result = asyncio.run(engine.run("external", knowledge_base_ids=[kb.id],
            subquestions=["external"], requirements=[EvidenceRequirement("fact", ("supported fact",))]))
        assert result["metrics"]["llm_tokens"] == {"input_tokens": 12, "output_tokens": 4}
        assert result["metrics"]["llm_calls_completed"] == 1
        assert result["metrics"]["actual_cost_usd"] is None
        assert result["metrics"]["tool_execution"]["quick"] == "injected"


def test_synthesis_failure_preserves_sources_and_metrics(tmp_path):
    from deepresearch_kb.sufficiency import EvidenceRequirement
    store = KnowledgeStore(tmp_path / "failure.sqlite")

    class BrokenReporter:
        async def write_report(self, **kwargs):
            raise RuntimeError("sensitive provider detail must not be persisted")

    async def quick(query):
        return [Evidence("fact", "supported fact", "external_web", "https://example.org", "web", "", 1, 0)]

    engine = ResearchEngine(store=store, quick_search=quick,
                            researcher_factory=lambda q: BrokenReporter())
    folder = tmp_path / "failed-run"
    result = asyncio.run(engine.run("external", knowledge_base_ids=[],
        subquestions=["external"], requirements=[EvidenceRequirement("fact", ("supported fact",))],
        output_dir=folder))
    assert result["metrics"]["status"] == "failed"
    assert result["metrics"]["failure_stage"] == "synthesis"
    assert result["metrics"]["error_type"] == "RuntimeError"
    assert json.loads((folder / "sources.json").read_text())[0]["text"] == "supported fact"
    assert set(p.name for p in folder.iterdir()) == {"run.json", "plan.json", "trace.json", "sources.json", "report.md"}
    assert "sensitive provider detail" not in (folder / "run.json").read_text()


@pytest.mark.parametrize("final_verdict", ["conflict", "unknown"])
def test_quick_conflict_escalates_and_deep_remains_unresolved(tmp_path, final_verdict):
    from deepresearch_kb.sufficiency import EvidenceRequirement
    store = KnowledgeStore(tmp_path / "conflict.sqlite")

    async def quick(query):
        return [Evidence("a", "supported fact", "external_web", "https://a.example", "a", "", 1, 0)]

    async def deep(query):
        return [Evidence("b", "other fact", "external_web", "https://b.example", "b", "", 1, 0)]

    class Checker:
        async def check(self, evidence):
            if not evidence:
                return {"status": "not_applicable", "pairs": []}
            verdict = "conflict" if len(evidence) == 1 else final_verdict
            return {"status": "reviewed", "conflict_detected": verdict == "conflict",
                    "pairs": [{"verdict": verdict}]}

    engine = ResearchEngine(store=store, quick_search=quick, deep_research=deep,
        researcher_factory=lambda q: _Researcher(), conflict_checker=Checker())
    result = asyncio.run(engine.run("external", knowledge_base_ids=[], subquestions=["external"],
        requirements=[EvidenceRequirement("fact", ("supported fact",))], output_dir=tmp_path / "run"))
    assert result["metrics"]["quick_calls"] == 1
    assert result["metrics"]["deep_calls"] == 1
    assert result["metrics"]["status"] == "incomplete"
    assert result["metrics"]["evidence_status"] == [final_verdict]
    assert len(result["trace"][0]["conflict_reviews"]) == 3
    assert len(result["sources"]) == 2
    assert "Research limitations:" in result["report"]
    assert final_verdict in result["report"]


def test_question_mapping_rejects_unmatched_requirement(tmp_path):
    from deepresearch_kb.sufficiency import EvidenceRequirement
    store = KnowledgeStore(tmp_path / "mapping.sqlite")
    engine = ResearchEngine(store=store, researcher_factory=lambda q: _Researcher())
    with pytest.raises(ValueError, match="exactly match"):
        asyncio.run(engine.run("external", knowledge_base_ids=[], subquestions=["external"],
            requirements={"a different question": EvidenceRequirement("r", ("fact",))}))


def test_question_mapping_follows_question_not_dictionary_order(tmp_path):
    from deepresearch_kb.sufficiency import EvidenceRequirement
    store = KnowledgeStore(tmp_path / "mapping.sqlite")
    async def quick(query):
        return [Evidence(query, query + " fact", "external_web", "https://example.org/" + query, query, "", 1, 0)]
    engine = ResearchEngine(store=store, researcher_factory=lambda q: _Researcher(), quick_search=quick)
    result = asyncio.run(engine.run("external", knowledge_base_ids=[], subquestions=["first", "second"],
        requirements={"second": EvidenceRequirement("r2", ("second fact",)),
                      "first": EvidenceRequirement("r1", ("first fact",))}))
    assert [t["requirement"]["id"] for t in result["trace"]] == ["r1", "r2"]
    assert result["metrics"]["requirement_origin"] == "caller_explicit_question_mapping"


def test_existing_artifact_directory_rejected_before_provider_call(tmp_path):
    store = KnowledgeStore(tmp_path / "existing.sqlite")
    def forbidden(query):
        raise AssertionError("must validate output before provider construction")
    engine = ResearchEngine(store=store, researcher_factory=forbidden)
    with pytest.raises(FileExistsError):
        asyncio.run(engine.run("query", knowledge_base_ids=[], output_dir=tmp_path))


@pytest.mark.parametrize("route", ["stop", "quick", "deep"])
def test_independent_query_to_report_case(tmp_path, route):
    from deepresearch_kb.sufficiency import EvidenceRequirement
    from deepresearch_kb.governance import VersionGovernance

    async def loader(path):
        return [{"raw_content": path.read_text(), "url": path.name}]

    store = KnowledgeStore(tmp_path / "case.sqlite", loader=loader)
    kb = store.create_knowledge_base(route)
    source = tmp_path / "architecture.txt"
    source.write_text("project SQLite internal baseline")
    version = asyncio.run(store.ingest(kb.id, source, logical_path="architecture.txt"))
    VersionGovernance(store).set_metadata(version.document_id, version.version,
        effective_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
    query = "our project SQLite latest decision"
    claim = "internal baseline" if route == "stop" else "external confirmation"

    class Researcher(_Researcher):
        async def plan_research(self, question):
            assert question == query
            return [question]

    class Checker:
        async def check(self, evidence):
            return {"status": "reviewed", "pairs": [], "conflict_detected": False}

    async def quick(question):
        assert route != "stop"
        text = "external confirmation" if route == "quick" else "unrelated search result"
        return [Evidence("quick", text, "external_web", "https://quick.example", "quick", "", 1, 0)]

    async def deep(question):
        assert route == "deep"
        return [Evidence("deep", "external confirmation", "external_web", "https://deep.example", "deep", "", 1, 0)]

    engine = ResearchEngine(store=store, quick_search=quick, deep_research=deep,
        researcher_factory=lambda q: Researcher(), conflict_checker=Checker(),
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc))
    folder = tmp_path / "run"
    result = asyncio.run(engine.run(query, knowledge_base_ids=[kb.id],
        requirements={query: EvidenceRequirement("explicit", (claim,))}, output_dir=folder))
    assert result["metrics"]["status"] == "completed"
    assert result["metrics"]["final_route_summary"] == [route]
    assert result["metrics"]["quick_calls"] == int(route != "stop")
    assert result["metrics"]["deep_calls"] == int(route == "deep")
    trace = json.loads((folder / "trace.json").read_text())[0]
    assert trace["source_policy"] == "hybrid"
    assert trace["internal_evidence"][0]["status"] == "active"
    assert len(trace["decisions"]) == {"stop": 1, "quick": 2, "deep": 3}[route]
    sources = [Evidence(**row) for row in json.loads((folder / "sources.json").read_text())]
    assert (folder / "report.md").read_text() == "REPORT\n" + render_evidence_context(sources)
    assert json.loads((folder / "plan.json").read_text())["query"] == query
    assert json.loads((folder / "run.json").read_text())["llm_tokens"] is None


def test_deep_budget_is_shared_across_subquestions(tmp_path):
    from deepresearch_kb.sufficiency import EvidenceRequirement
    store = KnowledgeStore(tmp_path / "budget.sqlite")
    async def quick(query):
        return []
    async def deep(query):
        return []
    engine = ResearchEngine(store=store, quick_search=quick, deep_research=deep,
        researcher_factory=lambda q: _Researcher(), max_deep_calls=1)
    result = asyncio.run(engine.run("external", knowledge_base_ids=[],
        subquestions=["first", "second"], requirements=[
            EvidenceRequirement("first", ("missing",)), EvidenceRequirement("second", ("missing",))]))
    assert result["metrics"]["deep_calls"] == 1
    assert result["metrics"]["status"] == "incomplete"
    assert "budget exhausted" in result["trace"][1]["decisions"][-1]["reason"]
