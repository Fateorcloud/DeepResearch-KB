import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from deepresearch_kb.api import create_app
from deepresearch_kb.claim_suggestions import ClaimSuggester, MAX_CLAIM_LENGTH
from deepresearch_kb.engine import ResearchEngine
from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.local_control import AllowedRoot, CloudClient, LocalControlService, create_local_app
from deepresearch_kb.services.research import ResearchService
from deepresearch_kb.services.tasks import TaskService
from tests.deepresearch_kb.auth_support import bearer_client, configured_auth
from tests.deepresearch_kb.test_semantic_claims import evidence, reviewer


def api_client(tmp_path, output):
    store = KnowledgeStore(tmp_path / "kb.sqlite")
    auth = configured_auth(store.database)
    llm = AsyncMock(return_value=output)
    app = create_app(store=store, auth=auth, artifact_root=tmp_path / "tasks",
                     backup_root=tmp_path / "backups", claims_suggester=ClaimSuggester(llm))
    return bearer_client(app, auth), llm


@pytest.mark.parametrize("body", [
    {}, {"query": " "}, {"query": "q", "extra": True},
    {"query": "q", "max_claims": 0}, {"query": "q", "max_claims": 9},
    {"query": "q", "max_claims": True}, {"query": "q", "max_claims": "4"},
])
def test_suggest_endpoint_validates_parameters(tmp_path, body):
    client, llm = api_client(tmp_path, '{"claims":["claim"]}')
    with client:
        assert client.post("/api/research/claims/suggest", json=body).status_code == 422
    llm.assert_not_awaited()


def test_suggest_endpoint_cleans_deduplicates_limits_and_marks_source(tmp_path):
    client, llm = api_client(tmp_path, json.dumps({"claims": [
        "", "   ", " 支持 OAuth2 ", "支持 OAuth2", "单个\n要点", "长" * 200, "最后"]}))
    with client:
        response = client.post("/api/research/claims/suggest", json={"query": "q"})
        assert response.status_code == 200
        assert response.json() == {"source": "generated", "claims": [
            "支持 OAuth2", "单个 要点", "长" * MAX_CLAIM_LENGTH, "最后"]}
        limited = client.post("/api/research/claims/suggest", json={"query": "q", "max_claims": 1})
        assert limited.json()["claims"] == ["支持 OAuth2"]
    assert llm.await_count == 2


@pytest.mark.parametrize("output", ['{"claims":[]}', '{"claims":[" "]}', 'not json', '[]', '{"claims":[5]}'])
def test_suggest_failure_is_explicit_and_redacted(tmp_path, output):
    client, _ = api_client(tmp_path, output)
    with client:
        response = client.post("/api/research/claims/suggest", json={"query": "q"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "claims_generation_failed"
    assert "claims" not in response.json()


def test_suggest_provider_exception_is_redacted(tmp_path):
    client, llm = api_client(tmp_path, "unused")
    llm.side_effect = RuntimeError("secret-provider-key")
    with client:
        response = client.post("/api/research/claims/suggest", json={"query": "q"})
    assert response.status_code == 503
    assert "secret-provider-key" not in response.text


def test_research_still_requires_human_confirmed_claims(tmp_path):
    client, llm = api_client(tmp_path, '{"claims":["claim"]}')
    with client:
        response = client.post("/api/research", json={"query": "q", "knowledge_base_ids": []})
    assert response.status_code == 422
    llm.assert_not_awaited()


@pytest.mark.parametrize("fail,expected_source", [(False, "generated"), (True, "query_fallback")])
def test_local_control_records_claims_source_in_run_and_trace(tmp_path, fail, expected_source):
    store = KnowledgeStore(tmp_path / "kb.sqlite")
    kb = store.create_knowledge_base("test")
    query = "核对支持异步函数"
    semantic, _ = reviewer()

    def factory(question):
        return SimpleNamespace(
            research_conductor=SimpleNamespace(plan_research=AsyncMock(return_value=[query])),
            write_report=AsyncMock(return_value="verified"))

    engine = ResearchEngine(store=store, quick_search=AsyncMock(return_value=[evidence(query)]),
        deep_research=AsyncMock(return_value=[]), researcher_factory=factory, claim_reviewer=semantic)
    tasks = TaskService(ResearchService(engine), tmp_path / "tasks")
    service = LocalControlService(AllowedRoot(tmp_path), CloudClient(None, None), store, tasks)
    llm = AsyncMock(return_value='{"claims": ["支持异步函数"]}')
    if fail:
        llm.side_effect = RuntimeError("secret-key")
    app = create_local_app(root=tmp_path, server=None, token=None, service=service,
        allowed_hosts={"testserver", "testclient"}, control_token="test-token",
        claims_suggester=ClaimSuggester(llm))
    with TestClient(app, headers={"X-Local-Control-Token": "test-token"}) as client:
        response = client.post("/api/local/research", json={
            "query": query, "knowledge_base_ids": [kb.id], "max_deep_calls": 0,
            "source_mode": "hybrid"})
        assert response.status_code == 200
        assert response.json()["claims_source"] == expected_source
        assert response.json()["claims"] == ([query] if fail else ["支持异步函数"])
        task_id = response.json()["task_id"]
        for _ in range(100):
            task = client.get(f"/api/local/research/{task_id}").json()
            if task["status"] in {"completed", "failed"}:
                break
            time.sleep(.01)
        assert task["status"] == "completed"
        metrics = client.get(f"/api/local/research/{task_id}/metrics").json()
        trace = client.get(f"/api/local/research/{task_id}/trace").json()
        assert metrics["claims_source"] == trace[0]["claims_source"] == expected_source
        assert "secret-key" not in json.dumps([metrics, trace])
    llm.assert_awaited_once()
