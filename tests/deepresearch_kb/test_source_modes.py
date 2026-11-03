import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

import deepresearch_kb.engine as engine_module
from deepresearch_kb.api import create_app
from deepresearch_kb.claim_suggestions import ClaimsGenerationError
from deepresearch_kb.engine import ResearchEngine
from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.local_control import AllowedRoot, CloudClient, LocalControlService, create_local_app
from deepresearch_kb.models import Evidence
from deepresearch_kb.services.tasks import TaskService
from deepresearch_kb.sufficiency import EvidenceRequirement, assess_requirements
from tests.deepresearch_kb.auth_support import configured_auth


CLAIM = "公司报销上限为 100 元"
QUESTION = "2023 年公司的报销标准是什么"


def evidence(kind, text=CLAIM):
    return Evidence(kind, text, "local_import" if kind == "local" else "external_web",
                    f"file:///{kind}.txt" if kind == "local" else f"https://example.test/{kind}",
                    f"{kind}.txt", "document" if kind == "local" else "", 1, 1.0)


class LexicalReviewer:
    async def assess(self, requirement, items):
        result = assess_requirements([requirement], items)[0]
        return {"satisfied": result.satisfied, "conflict_detected": False, "claims": []}


@pytest.fixture
def engine_factory(monkeypatch):
    def make(*, local=(), quick=(), deep=(), checker=None):
        events = []

        def retrieve(*args, **kwargs):
            events.append("local")
            return list(local)

        async def search(kind, items):
            events.append(kind)
            return list(items)

        governed = SimpleNamespace(as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
                                   retrieve=Mock(side_effect=retrieve))
        monkeypatch.setattr(engine_module, "GovernedKnowledge", lambda *args, **kwargs: governed)
        writer = SimpleNamespace(
            cfg=SimpleNamespace(llm_kwargs={}),
            research_conductor=SimpleNamespace(plan_research=AsyncMock(return_value=[QUESTION])),
            write_report=AsyncMock(side_effect=lambda **kwargs: kwargs["ext_context"]))
        async def quick_search(question):
            return await search("quick", quick)

        async def deep_search(question):
            return await search("deep", deep)

        engine = ResearchEngine(
            store=object(), quick_search=AsyncMock(side_effect=quick_search),
            deep_research=AsyncMock(side_effect=deep_search),
            researcher_factory=lambda question: writer, claim_reviewer=LexicalReviewer(),
            conflict_checker=checker or SimpleNamespace(
                check=AsyncMock(return_value={"status": "reviewed", "pairs": []})))
        return engine, governed, writer, events

    return make


async def run_engine(engine, mode, *, output_dir=None, max_deep_calls=1, questions=None):
    return await engine.run(
        QUESTION, source_mode=mode, knowledge_base_ids=[] if mode == "web" else ["kb"],
        requirements=EvidenceRequirement("claim", (CLAIM,)),
        subquestions=questions or [QUESTION], output_dir=output_dir, max_deep_calls=max_deep_calls)


async def test_web_mode_ignores_internal_keywords_and_uses_standard_search(engine_factory):
    engine, governed, writer, events = engine_factory(local=[evidence("local")], quick=[evidence("quick")])
    result = await engine.run("our internal project", knowledge_base_ids=[],
        requirements=EvidenceRequirement("r", (CLAIM,)), subquestions=["our internal project"])
    governed.retrieve.assert_not_called()
    engine.quick_search.assert_awaited_once_with("our internal project")
    engine.deep_research.assert_not_awaited()
    assert events == ["quick"]
    assert result["metrics"]["source_mode"] == "web"
    assert result["metrics"]["research_depth"] == "medium"
    assert writer.cfg.reasoning_effort == "medium"
    assert result["trace"][0]["quick_search_label"] == "标准搜索"


@pytest.mark.parametrize("items,sufficient", [([], False), ([evidence("local")], True)])
async def test_local_mode_never_calls_web_and_records_insufficiency(engine_factory, items, sufficient):
    engine, governed, writer, events = engine_factory(local=items)
    result = await run_engine(engine, "local")
    governed.retrieve.assert_called_once_with(["kb"], QUESTION, limit=5)
    engine.quick_search.assert_not_awaited()
    engine.deep_research.assert_not_awaited()
    assert events == ["local"]
    assert result["trace"][0]["retrieval_calls"] == {"local": 1, "quick": 0, "deep": 0}
    assert result["metrics"]["evidence_status"] == ["sufficient" if sufficient else "insufficient"]
    if not sufficient:
        assert result["metrics"]["status"] == "incomplete"
        assert "Research limitations" in result["report"]
        writer.write_report.assert_not_awaited()


@pytest.mark.parametrize("local,quick,deep,budget,expected", [
    ([evidence("local")], [], [], 1, ["local"]),
    ([], [evidence("quick")], [], 1, ["local", "quick"]),
    ([], [], [evidence("deep")], 1, ["local", "quick", "deep"]),
    ([], [], [evidence("deep")], 0, ["local", "quick"]),
])
async def test_hybrid_chinese_question_uses_local_then_quick_then_deep(
        engine_factory, local, quick, deep, budget, expected):
    engine, governed, _, events = engine_factory(local=local, quick=quick, deep=deep)
    result = await run_engine(engine, "hybrid", max_deep_calls=budget)
    governed.retrieve.assert_called_once_with(["kb"], QUESTION, limit=5)
    assert events == expected
    assert result["trace"][0]["source_mode"] == "hybrid"
    assert result["metrics"]["evidence_status"] == ["insufficient" if budget == 0 else "sufficient"]


async def test_hybrid_unknown_local_review_still_tries_quick_before_deep(engine_factory):
    checker = SimpleNamespace(check=AsyncMock(side_effect=[
        {"status": "unknown", "pairs": []}, {"status": "reviewed", "pairs": []},
        {"status": "reviewed", "pairs": []}]))
    engine, _, _, events = engine_factory(deep=[evidence("deep")], checker=checker)
    result = await run_engine(engine, "hybrid")
    assert events == ["local", "quick", "deep"]
    assert result["metrics"]["evidence_status"] == ["sufficient"]


async def test_trace_and_run_record_actual_calls_per_question_and_shared_budget(engine_factory, tmp_path):
    engine, _, _, events = engine_factory(deep=[evidence("deep")])
    result = await run_engine(engine, "hybrid", output_dir=tmp_path / "run", questions=["第一问", "第二问"])
    trace = json.loads((tmp_path / "run" / "trace.json").read_text())
    metrics = json.loads((tmp_path / "run" / "run.json").read_text())
    assert events == ["local", "quick", "deep", "local", "quick"]
    assert [row["retrieval_calls"] for row in trace] == [
        {"local": 1, "quick": 1, "deep": 1}, {"local": 1, "quick": 1, "deep": 0}]
    assert all(row["source_mode"] == "hybrid" for row in trace)
    assert metrics["source_mode"] == "hybrid"
    assert (metrics["local_calls"], metrics["quick_calls"], metrics["deep_calls"]) == (2, 2, 1)
    assert metrics["question_retrieval"] == [{
        "question": row["question"], "source_mode": "hybrid",
        "retrieval_calls": row["retrieval_calls"], "quick_search_label": "快速搜索",
    } for row in trace]
    assert result["metrics"]["max_deep_calls"] == 1


@pytest.mark.parametrize("budget,expected", [(0, ["quick"]), (1, ["quick", "deep"])])
async def test_web_standard_search_precedes_deep_and_respects_budget(engine_factory, budget, expected):
    engine, governed, _, events = engine_factory(deep=[evidence("deep")])
    updates = []
    result = await engine.run(
        QUESTION, knowledge_base_ids=[], requirements=EvidenceRequirement("r", (CLAIM,)),
        subquestions=[QUESTION], max_deep_calls=budget, progress=updates.append)
    assert events == expected
    governed.retrieve.assert_not_called()
    assert any(update["phase"] == "standard_research" for update in updates)
    assert all(update["phase"] != "quick_research" for update in updates)
    assert result["trace"][0]["retrieval_calls"] == {"local": 0, "quick": 1, "deep": budget}
    assert result["metrics"]["evidence_status"] == ["sufficient" if budget else "insufficient"]


async def test_local_partial_evidence_is_reported_with_existing_limitations(engine_factory):
    engine, _, writer, _ = engine_factory(local=[evidence("local", "unrelated company fact")])
    result = await run_engine(engine, "local")
    assert result["metrics"]["status"] == "incomplete"
    assert "Research limitations" in writer.write_report.await_args.kwargs["ext_context"]
    assert "insufficient" in result["report"]


@pytest.fixture
async def source_app_factory(tmp_path):
    clients = []

    def make(surface="api", *, research=None, claims_suggester=None, store=None, artifact_root=None):
        folder = tmp_path / f"app-{len(clients)}"
        store = store or KnowledgeStore(folder / "kb.sqlite")
        if not store.list_knowledge_bases():
            store.create_knowledge_base("first")
            store.create_knowledge_base("second")
        research = research or SimpleNamespace(run=AsyncMock(return_value={"metrics": {"status": "completed"}}))
        root = artifact_root or folder / "tasks"
        if surface == "local":
            folder.mkdir(parents=True, exist_ok=True)
            service = LocalControlService(AllowedRoot(folder), CloudClient(None, None), store,
                                          TaskService(research, root))
            app = create_local_app(root=folder, server=None, token=None, service=service,
                control_token="source-tests", allowed_hosts={"127.0.0.1", "testserver"},
                claims_suggester=claims_suggester)
            headers = {"X-Local-Control-Token": "source-tests"}
            prefix = "/api/local/research"
        else:
            auth = configured_auth(store.database)
            app = create_app(store=store, auth=auth, research=research, artifact_root=root,
                             backup_root=folder / "backups", claims_suggester=claims_suggester)
            headers = {"Authorization": f"Bearer {auth.issue_cli_token('sources').token}"}
            prefix = "/api/research"
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                   base_url="http://testserver", headers=headers)
        clients.append(client)
        return SimpleNamespace(client=client, prefix=prefix, store=store, root=root, research=research,
                               kb_ids=[kb.id for kb in store.list_knowledge_bases()])

    yield make
    for client in clients:
        await client.aclose()
    await asyncio.sleep(0)


async def task_status(app, task_id):
    async with asyncio.timeout(3):
        while True:
            task = (await app.client.get(f"{app.prefix}/{task_id}")).json()
            if task["status"] in {"completed", "failed", "cancelled"}:
                return task
            await asyncio.sleep(0)


@pytest.mark.parametrize("surface", ["api", "local"])
async def test_both_endpoints_default_to_web_without_knowledge_bases(source_app_factory, surface):
    app = source_app_factory(surface)
    response = await app.client.post(app.prefix, json={"query": QUESTION, "required_claims": [CLAIM]})
    assert response.status_code == 200
    task = await task_status(app, response.json()["task_id"])
    assert task["source_mode"] == "web"
    assert task["knowledge_base_ids"] == []
    assert app.research.run.await_args.kwargs["source_mode"] == "web"


@pytest.mark.parametrize("surface", ["api", "local"])
@pytest.mark.parametrize("mode,count,types", [
    ("web", 0, []), ("web", 0, ["external_web"]),
    ("local", 1, []), ("local", 2, ["local_import", "web_upload"]),
    ("hybrid", 1, []), ("hybrid", 2, ["local_import", "web_upload", "external_web"]),
])
async def test_both_endpoints_accept_valid_source_combinations(source_app_factory, surface, mode, count, types):
    app = source_app_factory(surface)
    response = await app.client.post(app.prefix, json={
        "query": QUESTION, "required_claims": [CLAIM], "source_mode": mode,
        "knowledge_base_ids": app.kb_ids[:count], "required_source_types": types})
    assert response.status_code == 200
    task = await task_status(app, response.json()["task_id"])
    assert task["source_mode"] == mode
    assert app.research.run.await_args.kwargs["knowledge_base_ids"] == tuple(app.kb_ids[:count])


@pytest.mark.parametrize("surface", ["api", "local"])
@pytest.mark.parametrize("mode,count,types,code", [
    ("local", 0, [], "source_mode_requires_knowledge_base"),
    ("hybrid", 0, [], "source_mode_requires_knowledge_base"),
    ("web", 1, [], "web_mode_disallows_knowledge_bases"),
    ("web", 2, [], "web_mode_disallows_knowledge_bases"),
    ("local", 1, ["external_web"], "source_mode_source_type_conflict"),
    ("web", 0, ["local_import"], "source_mode_source_type_conflict"),
    ("web", 0, ["web_upload"], "source_mode_source_type_conflict"),
    ("unknown", 0, [], "invalid_source_mode"),
    ("hybrid", -1, [], "invalid_request"),
    ("hybrid", -2, [], "invalid_request"),
])
async def test_both_endpoints_reject_invalid_source_combinations(
        source_app_factory, surface, mode, count, types, code):
    app = source_app_factory(surface)
    kb_ids = [""] if count == -1 else [app.kb_ids[0]] * 2 if count == -2 else app.kb_ids[:count]
    response = await app.client.post(app.prefix, json={
        "query": QUESTION, "required_claims": [CLAIM], "source_mode": mode,
        "knowledge_base_ids": kb_ids, "required_source_types": types})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    app.research.run.assert_not_awaited()
    assert (await app.client.get(app.prefix)).json() == []


@pytest.mark.parametrize("mode", ["web", "local", "hybrid"])
async def test_retry_preserves_source_mode_after_restart(source_app_factory, mode):
    research = SimpleNamespace(run=AsyncMock(side_effect=[TimeoutError("private"), {"metrics": {"status": "completed"}}]))
    app = source_app_factory(research=research)
    response = await app.client.post(app.prefix, json={
        "query": QUESTION, "required_claims": [CLAIM], "source_mode": mode,
        "knowledge_base_ids": [] if mode == "web" else app.kb_ids})
    original_id = response.json()["task_id"]
    original = await task_status(app, original_id)
    assert original["status"] == "failed"
    restored = source_app_factory(research=research, store=app.store, artifact_root=app.root)
    response = await restored.client.post(f"{restored.prefix}/{original_id}/retry")
    assert response.status_code == 200
    new_id = response.json()["task_id"]
    task = await task_status(restored, new_id)
    assert task["source_mode"] == mode
    assert task["retry_of"] == original_id
    assert research.run.await_args.kwargs["source_mode"] == mode
    assert (await restored.client.get(f"{restored.prefix}/{original_id}")).json() == original


async def test_pre_source_mode_record_returns_retry_unavailable(source_app_factory):
    research = SimpleNamespace(run=AsyncMock(side_effect=TimeoutError("private")))
    app = source_app_factory(research=research)
    response = await app.client.post(app.prefix, json={"query": QUESTION, "required_claims": [CLAIM]})
    original_id = response.json()["task_id"]
    await task_status(app, original_id)
    index = app.root / ".research-tasks.json"
    payload = json.loads(index.read_text())
    del payload["tasks"][0]["source_mode"]
    index.write_text(json.dumps(payload))
    restored = source_app_factory(store=app.store, artifact_root=app.root)
    response = await restored.client.post(f"{restored.prefix}/{original_id}/retry")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "retry_unavailable"
    restored.research.run.assert_not_awaited()


@pytest.mark.parametrize("provenance", ["explicit", "generated", "query_fallback"])
async def test_local_details_and_history_show_actual_claims_and_provenance(source_app_factory, provenance):
    suggester = SimpleNamespace(suggest=AsyncMock(return_value={"claims": [CLAIM], "source": "generated"}))
    if provenance == "query_fallback":
        suggester.suggest.side_effect = ClaimsGenerationError("private error")
    app = source_app_factory("local", claims_suggester=suggester)
    response = await app.client.post(app.prefix, json={
        "query": QUESTION, "required_claims": [CLAIM] if provenance == "explicit" else []})
    assert response.status_code == 200
    expected = [QUESTION] if provenance == "query_fallback" else [CLAIM]
    task = await task_status(app, response.json()["task_id"])
    history = (await app.client.get(app.prefix)).json()[0]
    for record in (task, history):
        assert record["required_claims"] == expected
        assert record["claims_source"] == provenance
    assert response.json()["claims"] == expected
    assert response.json()["claims_source"] == provenance


async def test_local_suggest_endpoint_uses_current_query_and_four_claims(source_app_factory):
    suggester = SimpleNamespace(suggest=AsyncMock(return_value={"claims": [CLAIM], "source": "generated"}))
    app = source_app_factory("local", claims_suggester=suggester)
    response = await app.client.post("/api/research/claims/suggest", json={"query": QUESTION, "max_claims": 4})
    assert response.status_code == 200
    assert response.json()["claims"] == [CLAIM]
    suggester.suggest.assert_awaited_once_with(QUESTION, 4)
