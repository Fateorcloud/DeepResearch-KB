import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from deepresearch_kb.api import create_app
from deepresearch_kb.engine import ResearchEngine
from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.models import Evidence
from deepresearch_kb.services.research import ResearchService
from deepresearch_kb.services.tasks import TaskService
from deepresearch_kb.sufficiency import EvidenceRequirement


def _research_body(kb_id=None):
    return {
        "query": "Which storage decision is current?",
        "knowledge_base_ids": [kb_id] if kb_id else [],
        "required_claims": ["SQLite is the current storage decision"],
        "required_source_types": ["web_upload", "external_web"],
        "minimum_distinct_sources": 2,
        "require_current_version": True,
        "as_of": "2026-09-15T10:00:00+08:00",
        "max_deep_calls": 2,
    }


def _write_artifacts(output_dir):
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    (root / "report.md").write_text("# Verified report", encoding="utf-8")
    (root / "sources.json").write_text(json.dumps([{"source_uri": "https://example.test"}]), encoding="utf-8")
    (root / "trace.json").write_text(json.dumps([{"final_route": "quick"}]), encoding="utf-8")
    metrics = {"status": "completed", "quick_calls": 1, "deep_calls": 0}
    (root / "run.json").write_text(json.dumps(metrics), encoding="utf-8")
    return {"report": "# Verified report", "sources": [], "trace": [], "metrics": metrics}


class ControlledEngine:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.call = None

    async def run(self, query, **kwargs):
        self.call = (query, kwargs)
        self.started.set()
        while not self.release.is_set():
            await asyncio.sleep(0.005)
        return _write_artifacts(kwargs["output_dir"])


def _wait_for_status(client, task_id, expected, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/research/{task_id}")
        assert response.status_code == 200
        if response.json()["status"] == expected:
            return response.json()
        time.sleep(0.01)
    pytest.fail(f"task did not reach {expected}")


def test_http_research_composes_engine_contract_lifecycle_and_artifacts(tmp_path):
    store = KnowledgeStore(tmp_path / "kb.sqlite")
    kb = store.create_knowledge_base("project")
    engine = ControlledEngine()
    app = create_app(store=store, engine=engine, artifact_root=tmp_path / "tasks")

    with TestClient(app) as client:
        response = client.post("/api/research", json=_research_body(kb.id))
        assert response.status_code == 200
        assert set(response.json()) == {"task_id"}
        task_id = response.json()["task_id"]
        assert engine.started.wait(1)

        running = _wait_for_status(client, task_id, "running")
        assert running["error"] is None
        assert "artifact_path" not in running
        assert client.get(f"/api/research/{task_id}/report").status_code == 409

        query, options = engine.call
        requirement = options["requirements"]
        assert query == _research_body(kb.id)["query"]
        assert options["knowledge_base_ids"] == (kb.id,)
        assert requirement == EvidenceRequirement(
            "http-request", ("SQLite is the current storage decision",),
            ("web_upload", "external_web"), 2, True)
        assert options["as_of"] == datetime(2026, 9, 15, 2, tzinfo=timezone.utc)
        assert options["max_deep_calls"] == 2

        engine.release.set()
        completed = _wait_for_status(client, task_id, "completed")
        assert completed["completed_at"] is not None
        assert client.get(f"/api/research/{task_id}/report").json() == "# Verified report"
        assert client.get(f"/api/research/{task_id}/sources").json()[0]["source_uri"] == "https://example.test"
        assert client.get(f"/api/research/{task_id}/trace").json()[0]["final_route"] == "quick"
        assert client.get(f"/api/research/{task_id}/metrics").json()["status"] == "completed"


@pytest.mark.parametrize("change", [
    {"required_claims": []},
    {"required_claims": [" "]},
    {"required_source_types": ["database"]},
    {"minimum_distinct_sources": 0},
    {"as_of": "2026-09-15T10:00:00"},
    {"max_deep_calls": -1},
])
def test_http_rejects_invalid_evidence_requirement(tmp_path, change):
    body = _research_body()
    body.update(change)
    client = TestClient(create_app(store=KnowledgeStore(tmp_path / "kb.sqlite"),
                                   engine=AsyncMock(), artifact_root=tmp_path / "tasks"))
    response = client.post("/api/research", json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_request"


def test_http_rejects_unknown_knowledge_base_before_scheduling(tmp_path):
    engine = AsyncMock()
    client = TestClient(create_app(store=KnowledgeStore(tmp_path / "kb.sqlite"),
                                   engine=engine, artifact_root=tmp_path / "tasks"))
    response = client.post("/api/research", json=_research_body("missing"))
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "knowledge_base_not_found"
    engine.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_service_exposes_queued_running_completed(tmp_path):
    started = asyncio.Event()
    release = asyncio.Event()

    class Research:
        async def run(self, query, **kwargs):
            started.set()
            await release.wait()
            return _write_artifacts(kwargs["output_dir"])

    tasks = TaskService(Research(), tmp_path / "tasks")
    task = tasks.create("query", [], requirements=EvidenceRequirement("r", ("claim",)))
    assert tasks.get(task.id).status == "queued"
    await started.wait()
    assert tasks.get(task.id).status == "running"
    release.set()
    while tasks.get(task.id).status != "completed":
        await asyncio.sleep(0)
    assert tasks.get(task.id).completed_at is not None


@pytest.mark.asyncio
async def test_research_service_calls_engine_interface_with_explicit_requirement(tmp_path):
    engine = AsyncMock()
    engine.run.return_value = {"metrics": {"status": "completed"}}
    service = ResearchService(engine)
    requirement = EvidenceRequirement("r", ("claim",), ("external_web",), 1, True)
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)

    await service.run("query", knowledge_base_ids=["kb"], requirements=requirement,
                      output_dir=tmp_path / "run", as_of=as_of, max_deep_calls=3)

    engine.run.assert_awaited_once_with(
        "query", knowledge_base_ids=["kb"], requirements=requirement,
        output_dir=tmp_path / "run", as_of=as_of, max_deep_calls=3)


@pytest.mark.asyncio
async def test_task_failure_is_structured_and_redacted(tmp_path):
    secret = "sk-provider-secret HOME=/private/config"

    class BrokenResearch:
        async def run(self, query, **kwargs):
            raise RuntimeError(secret)

    tasks = TaskService(BrokenResearch(), tmp_path / "tasks")
    task = tasks.create("query", [], requirements=EvidenceRequirement("r", ("claim",)))
    while tasks.get(task.id).status not in ("completed", "failed"):
        await asyncio.sleep(0)
    payload = tasks.get(task.id)
    assert payload.status == "failed"
    assert payload.error.code == "research_failed"
    assert secret not in repr(payload)


def test_http_provider_failure_does_not_expose_exception_or_server_path(tmp_path):
    secret = "sk-live-provider-secret"

    class BrokenProvider:
        @property
        def research_conductor(self):
            return self

        async def plan_research(self, query):
            return [query]

        async def write_report(self, **kwargs):
            raise RuntimeError(secret)

    async def quick_search(query):
        return [Evidence("web", "provider-supported claim", "external_web",
                         "https://example.test", "web", "", 1, 1.0)]

    store = KnowledgeStore(tmp_path / "kb.sqlite")
    engine = ResearchEngine(store=store, quick_search=quick_search,
                            researcher_factory=lambda query: BrokenProvider())
    artifact_root = tmp_path / "private-tasks"
    app = create_app(store=store, engine=engine, artifact_root=artifact_root)
    body = _research_body()
    body.update({"query": "What is the storage decision?",
                 "required_claims": ["provider-supported claim"],
                 "required_source_types": ["external_web"],
                 "minimum_distinct_sources": 1,
                 "max_deep_calls": 0})
    with TestClient(app) as client:
        task_id = client.post("/api/research", json=body).json()["task_id"]
        failed = _wait_for_status(client, task_id, "failed")
        serialized = json.dumps(failed)
        assert failed["error"] == {"code": "research_failed", "message": "Research task failed"}
        assert secret not in serialized
        assert str(tmp_path) not in serialized
        artifact_response = client.get(f"/api/research/{task_id}/report")
        assert artifact_response.status_code == 409
        assert secret not in artifact_response.text
        run = (artifact_root / task_id / "run.json").read_text(encoding="utf-8")
        assert json.loads(run)["failure_stage"] == "synthesis"
        assert secret not in run
