import asyncio
import errno
import gc
import json
import os
import sqlite3
import stat
import weakref
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from deepresearch_kb.api import create_app
from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.services.tasks import ResearchTask, TaskError, TaskService
from deepresearch_kb.sufficiency import EvidenceRequirement
from tests.deepresearch_kb.auth_support import configured_auth


SAVED_REQUEST_FIELDS = {
    "query", "knowledge_base_ids", "required_claims", "required_source_types",
    "minimum_distinct_sources", "require_current_version", "as_of",
    "max_deep_calls", "output_language", "research_depth", "claims_source",
    "requirement_id",
    "source_mode",
}


class ControlledResearch:
    """Each call waits for an explicit event, with optional deterministic failures."""

    def __init__(self, failures=None):
        self.calls = []
        self.releases = []
        self.failures = failures or {}

    async def run(self, query, **options):
        index = len(self.calls)
        release = asyncio.Event()
        self.releases.append(release)
        self.calls.append((query, options))
        folder = options["output_dir"]
        folder.mkdir(parents=True)
        (folder / "report.md").write_text("partial report", encoding="utf-8")
        await release.wait()
        if index in self.failures:
            raise self.failures[index]
        (folder / "report.md").write_text("complete report", encoding="utf-8")
        return {"metrics": {"status": "completed"}, "sources": []}

    async def wait_started(self, index):
        async with asyncio.timeout(3):
            while len(self.calls) <= index:
                await asyncio.sleep(0)


@pytest.fixture
async def services(tmp_path, monkeypatch):
    monkeypatch.delenv("DRK_MAX_CONCURRENT_RESEARCH", raising=False)
    instances = []

    def make(research=None, **kwargs):
        service = TaskService(research or ControlledResearch(),
                              tmp_path / f"tasks-{len(instances)}", **kwargs)
        instances.append(service)
        return service

    yield make
    pending = [task for service in instances for task in service._background_tasks.values()]
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


@pytest.fixture
async def api_factory(tmp_path):
    clients = []

    def make(research=None, *, artifact_root=None, **kwargs):
        folder = tmp_path / f"app-{len(clients)}"
        store = KnowledgeStore(folder / "kb.sqlite")
        auth = configured_auth(store.database)
        research = research or ControlledResearch()
        root = artifact_root or folder / "tasks"
        app = create_app(store=store, auth=auth, research=research,
                         artifact_root=root, backup_root=folder / "backups", **kwargs)
        token = auth.issue_cli_token("task tests").token
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://testserver",
            headers={"Authorization": f"Bearer {token}"})
        clients.append(client)
        return client, research, root, store

    yield make
    for client in clients:
        response = await client.get("/api/research")
        for task in response.json():
            if task["status"] in {"queued", "running"}:
                await client.post(f"/api/research/{task['id']}/cancel")
        await client.aclose()


def request_body(**changes):
    return {
        "query": "research question", "knowledge_base_ids": [],
        "required_claims": ["first claim", "second claim"],
        "required_source_types": ["external_web"],
        "minimum_distinct_sources": 3, "require_current_version": True,
        "as_of": "2026-10-30T12:34:56+08:00", "max_deep_calls": 4,
        "output_language": "English", "research_depth": "high", **changes,
    }


async def submit(client, **changes):
    response = await client.post("/api/research", json=request_body(**changes))
    assert response.status_code == 200
    assert set(response.json()) == {"task_id"}
    return response.json()["task_id"]


async def wait_status(client, task_id, expected):
    async with asyncio.timeout(3):
        while True:
            response = await client.get(f"/api/research/{task_id}")
            assert response.status_code == 200
            if response.json()["status"] == expected:
                return response.json()
            await asyncio.sleep(0)


def records(root):
    return {task["id"]: task for task in json.loads(
        (root / ".research-tasks.json").read_text(encoding="utf-8"))["tasks"]}


def write_record(root, record):
    root.mkdir(parents=True, exist_ok=True)
    (root / ".research-tasks.json").write_text(
        json.dumps({"version": 1, "tasks": [record]}), encoding="utf-8")


def full_record(**changes):
    return asdict(ResearchTask(
        id="a" * 32, query="saved question", status="failed", phase="failed",
        required_claims=("saved claim",), required_source_types=("external_web",),
        minimum_distinct_sources=2, require_current_version=True,
        as_of="2026-10-30T12:34:56+08:00", max_deep_calls=3,
        output_language="English", research_depth="high", claims_source="generated",
        requirement_id="saved-requirement", retry_available=True, source_mode="web")) | changes


async def test_background_tasks_are_retained_until_completion(services):
    service = services()
    task = service.create("question", [])
    reference = weakref.ref(service._background_tasks[task.id])
    gc.collect()
    assert reference() is service._background_tasks[task.id]
    await service.research.wait_started(0)
    assert not reference().done()
    service.research.releases[0].set()
    await reference()
    await asyncio.sleep(0)
    assert task.status == "completed"
    assert service._background_tasks == {}


async def test_default_concurrency_queues_third_until_slot_released(services):
    service = services()
    tasks = [service.create(f"question-{index}", []) for index in range(3)]
    await service.research.wait_started(1)
    assert [task.status for task in tasks] == ["running", "running", "queued"]
    assert tasks[2].phase == "queued"
    assert tasks[2].started_at is None
    service.research.releases[0].set()
    await service.research.wait_started(2)
    assert [task.status for task in tasks] == ["completed", "running", "running"]
    for release in service.research.releases:
        release.set()
    await asyncio.gather(*list(service._background_tasks.values()))


@pytest.mark.parametrize("limit", [0, -1, False, 1.5])
def test_task_service_rejects_invalid_concurrency(tmp_path, limit):
    with pytest.raises(ValueError, match="max_concurrent_research"):
        TaskService(ControlledResearch(), tmp_path, max_concurrent_research=limit)


@pytest.mark.parametrize("environment,override,limit", [("1", None, 1), ("1", 2, 2)])
async def test_create_app_concurrency_environment_and_parameter_precedence(
        api_factory, monkeypatch, environment, override, limit):
    monkeypatch.setenv("DRK_MAX_CONCURRENT_RESEARCH", environment)
    client, research, _, _ = api_factory(max_concurrent_research=override)
    ids = [await submit(client, query=f"question-{index}") for index in range(3)]
    await research.wait_started(limit - 1)
    states = [(await client.get(f"/api/research/{task_id}")).json()["status"] for task_id in ids]
    assert states == ["running"] * limit + ["queued"] * (3 - limit)


@pytest.mark.parametrize("environment,override", [("2", 0), ("2", -1), ("0", None),
                                                      ("-1", None), ("invalid", None)])
def test_create_app_rejects_invalid_concurrency(tmp_path, monkeypatch, environment, override):
    monkeypatch.setenv("DRK_MAX_CONCURRENT_RESEARCH", environment)
    with pytest.raises(ValueError):
        create_app(database=tmp_path / "kb.sqlite", artifact_root=tmp_path / "tasks",
                   research=ControlledResearch(), max_concurrent_research=override)


async def test_timeout_records_type_redacts_sensitive_text_and_logs_traceback(services, caplog):
    secret = "sk-private-key https://private.example/token"
    research = ControlledResearch({0: TimeoutError(secret)})
    service = services(research, max_concurrent_research=1)
    first, second = [service.create(query, []) for query in ("first", "second")]
    await research.wait_started(0)
    first_background = service._background_tasks[first.id]
    research.releases[0].set()
    await first_background
    await research.wait_started(1)
    assert first.status == first.phase == "failed"
    assert first.error == TaskError("research_failed", "Research task failed: TimeoutError")
    assert secret not in repr(first)
    assert secret not in service.index_path.read_text(encoding="utf-8")
    assert first.id not in service._background_tasks
    assert second.status == "running"
    logged = next(record for record in caplog.records if record.name == "deepresearch_kb.services.tasks")
    assert logged.exc_info[0] is TimeoutError
    assert logged.exc_info[2] is not None
    assert secret in caplog.text


def test_persist_flushes_and_fsyncs_before_atomic_replace(tmp_path, monkeypatch):
    service = TaskService(ControlledResearch(), tmp_path)
    task = ResearchTask("a" * 32, "保存查询")
    service.tasks[task.id] = task
    temporary = service.index_path.with_suffix(".json.tmp")
    events = []
    real_open, real_replace, real_fsync = Path.open, Path.replace, os.fsync

    class TrackedFile:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def write(self, value):
            if "write" not in events:
                events.append("write")
            return self.handle.write(value)

        def flush(self):
            events.append("flush")
            self.handle.flush()

        def fileno(self):
            return self.handle.fileno()

    def open_file(path, *args, **kwargs):
        handle = real_open(path, *args, **kwargs)
        if path == temporary and args == ("w",):
            events.append("open_temporary")
            return TrackedFile(handle)
        return handle

    def fsync(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            events.append("fsync_directory")
        else:
            assert json.loads(temporary.read_text(encoding="utf-8"))["tasks"][0]["query"] == task.query
            assert temporary.stat().st_mode & 0o777 == 0o600
            events.append("fsync_file")
        return real_fsync(descriptor)

    def replace(path, target):
        assert path == temporary and target == service.index_path
        events.append("replace")
        return real_replace(path, target)

    monkeypatch.setattr(Path, "open", open_file)
    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(Path, "replace", replace)
    service._persist()
    expected = ["open_temporary", "write", "flush", "fsync_file", "replace"]
    if hasattr(os, "O_DIRECTORY"):
        expected.append("fsync_directory")
    assert events == expected
    assert service.index_path.stat().st_mode & 0o777 == 0o600
    assert not temporary.exists()


def test_persist_skips_unsupported_directory_fsync(tmp_path, monkeypatch):
    service = TaskService(ControlledResearch(), tmp_path)
    real_fsync = os.fsync

    def fsync(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError(errno.EINVAL, "directory fsync unsupported")
        return real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fsync)
    service._persist()
    assert records(tmp_path) == {}


def test_persist_file_fsync_failure_preserves_previous_index_and_cleans_temporary(tmp_path, monkeypatch):
    service = TaskService(ControlledResearch(), tmp_path)
    service._persist()
    previous = service.index_path.read_bytes()
    service.tasks["a" * 32] = ResearchTask("a" * 32, "new question")

    def fail_fsync(_descriptor):
        raise OSError(errno.EIO, "disk failure")

    monkeypatch.setattr(os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="disk failure"):
        service._persist()
    assert service.index_path.read_bytes() == previous
    assert not service.index_path.with_suffix(".json.tmp").exists()


async def test_cancel_running_task_persists_and_preserves_partial_artifacts(api_factory):
    client, research, root, _ = api_factory(max_concurrent_research=1)
    task_id = await submit(client)
    await research.wait_started(0)
    response = await client.post(f"/api/research/{task_id}/cancel")
    assert response.status_code == 200
    cancelled = response.json()
    assert cancelled["status"] == cancelled["phase"] == "cancelled"
    assert cancelled["error"] == {"code": "research_cancelled", "message": "Research task was cancelled"}
    assert cancelled["completed_at"] == cancelled["updated_at"]
    assert cancelled["completed_at"] is not None
    assert records(root)[task_id]["status"] == "cancelled"
    assert (root / task_id / "report.md").read_text(encoding="utf-8") == "partial report"
    artifact = await client.get(f"/api/research/{task_id}/report")
    assert artifact.status_code == 409
    assert artifact.json()["detail"]["code"] == "task_not_completed"
    next_id = await submit(client, query="next question")
    await research.wait_started(1)
    research.releases[1].set()
    await wait_status(client, next_id, "completed")


async def test_cancel_queued_task_preserves_capacity_for_next_waiter(api_factory):
    client, research, root, _ = api_factory(max_concurrent_research=1)
    first = await submit(client, query="first")
    await research.wait_started(0)
    queued = await submit(client, query="queued")
    third = await submit(client, query="third")
    assert (await client.get(f"/api/research/{queued}")).json()["phase"] == "queued"
    response = await client.post(f"/api/research/{queued}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["started_at"] is None
    assert "artifact_path" not in response.json()
    assert not (root / queued).exists()
    assert records(root)[queued]["status"] == "cancelled"
    assert len(research.calls) == 1
    research.releases[0].set()
    await research.wait_started(1)
    assert research.calls[1][0] == "third"
    assert (await client.get(f"/api/research/{third}")).json()["status"] == "running"
    research.releases[1].set()
    await wait_status(client, first, "completed")
    await wait_status(client, third, "completed")


async def test_cancel_before_coroutine_starts_is_persisted(services):
    service = services()
    task = service.create("question", [])
    background = service._background_tasks[task.id]
    await service.cancel(task.id)
    assert background.cancelled()
    assert task.status == task.phase == "cancelled"
    assert task.started_at is None
    assert service.research.calls == []
    assert service._background_tasks == {}
    assert records(service.root)[task.id]["error"]["code"] == "research_cancelled"


async def test_running_cancellation_propagates_and_removes_background_reference(services):
    service = services(max_concurrent_research=1)
    task = service.create("question", [])
    await service.research.wait_started(0)
    background = service._background_tasks[task.id]
    await service.cancel(task.id)
    assert background.cancelled()
    assert task.status == "cancelled"
    assert task.completed_at is not None
    assert service._background_tasks == {}
    assert records(service.root)[task.id]["status"] == "cancelled"


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
async def test_cancel_rejects_terminal_tasks_without_changes(api_factory, tmp_path, status):
    root = tmp_path / "saved"
    write_record(root, full_record(status=status, phase=status))
    client, research, _, _ = api_factory(artifact_root=root)
    before = (await client.get(f"/api/research/{'a' * 32}")).json()
    disk_before = (root / ".research-tasks.json").read_bytes()
    response = await client.post(f"/api/research/{'a' * 32}/cancel")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "task_not_cancellable"
    assert (await client.get(f"/api/research/{'a' * 32}")).json() == before
    assert (root / ".research-tasks.json").read_bytes() == disk_before
    assert research.calls == []


@pytest.mark.parametrize("action", ["cancel", "retry"])
async def test_task_actions_return_404_for_unknown_id(api_factory, action):
    client, research, _, _ = api_factory()
    response = await client.post(f"/api/research/{'f' * 32}/{action}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "task_not_found"
    assert research.calls == []


@pytest.mark.parametrize("status", ["failed", "cancelled"])
async def test_retry_replays_all_parameters_and_preserves_original(services, api_factory, status):
    research = ControlledResearch({0: TimeoutError("private detail")})
    service = services(research)
    original = service.create(
        "saved question", [], requirements=EvidenceRequirement(
            "saved-requirement", ("first claim", "second claim"),
            ("external_web",), 3, True),
        as_of=datetime.fromisoformat("2026-10-30T12:34:56+08:00"), max_deep_calls=4,
        output_language="English", research_depth="high", claims_source="generated")
    await research.wait_started(0)
    if status == "cancelled":
        await service.cancel(original.id)
    else:
        background = service._background_tasks[original.id]
        research.releases[0].set()
        await background
    assert original.status == status
    disk_before = records(service.root)[original.id]
    client, _, _, _ = api_factory(research, artifact_root=service.root)
    before = (await client.get(f"/api/research/{original.id}")).json()
    response = await client.post(f"/api/research/{original.id}/retry")
    assert response.status_code == 200
    assert set(response.json()) == {"task_id"}
    new_id = response.json()["task_id"]
    assert new_id != original.id
    await research.wait_started(1)
    new_task = (await client.get(f"/api/research/{new_id}")).json()
    assert new_task["retry_of"] == original.id
    assert new_task["retry_available"] is True
    for field in SAVED_REQUEST_FIELDS:
        assert new_task[field] == before[field]
    first_query, first_options = research.calls[0]
    new_query, new_options = research.calls[1]
    assert new_query == first_query
    assert {key: value for key, value in new_options.items() if key not in {"progress", "output_dir"}} == {
        key: value for key, value in first_options.items() if key not in {"progress", "output_dir"}}
    assert new_options["output_dir"] != first_options["output_dir"]
    research.releases[1].set()
    await wait_status(client, new_id, "completed")
    assert (await client.get(f"/api/research/{original.id}")).json() == before
    assert records(service.root)[original.id] == disk_before


@pytest.mark.parametrize("original_status", ["queued", "running"])
async def test_retry_research_interrupted_task_preserves_original(api_factory, tmp_path, original_status):
    root = tmp_path / "saved"
    write_record(root, full_record(status=original_status, phase=original_status))
    client, research, _, _ = api_factory(artifact_root=root)
    original_id = "a" * 32
    before = (await client.get(f"/api/research/{original_id}")).json()
    assert before["status"] == "failed"
    assert before["error"]["code"] == "research_interrupted"
    response = await client.post(f"/api/research/{original_id}/retry")
    assert response.status_code == 200
    new_id = response.json()["task_id"]
    assert new_id != original_id
    await research.wait_started(0)
    research.releases[0].set()
    new_task = await wait_status(client, new_id, "completed")
    assert new_task["retry_of"] == original_id
    assert all(new_task[field] == before[field] for field in SAVED_REQUEST_FIELDS)
    assert (await client.get(f"/api/research/{original_id}")).json() == before


@pytest.mark.parametrize("status", ["queued", "running", "completed"])
async def test_retry_rejects_active_or_completed_tasks_without_changes(api_factory, status):
    client, research, root, _ = api_factory(max_concurrent_research=1)
    task_id = await submit(client)
    await research.wait_started(0)
    if status == "queued":
        task_id = await submit(client, query="queued question")
    elif status == "completed":
        research.releases[0].set()
        await wait_status(client, task_id, "completed")
    before = (await client.get(f"/api/research/{task_id}")).json()
    assert before["status"] == status
    disk_before = (root / ".research-tasks.json").read_bytes()
    response = await client.post(f"/api/research/{task_id}/retry")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "task_not_retryable"
    assert (await client.get(f"/api/research/{task_id}")).json() == before
    assert (root / ".research-tasks.json").read_bytes() == disk_before


@pytest.mark.parametrize("missing", [None, *sorted(SAVED_REQUEST_FIELDS)])
async def test_retry_rejects_legacy_records_missing_parameters(api_factory, tmp_path, missing):
    root = tmp_path / "legacy"
    record = full_record()
    if missing is None:
        record = {"id": record["id"], "query": record["query"], "status": "failed"}
    else:
        del record[missing]
    write_record(root, record)
    # An unrelated write and a second restart must not make defaulted fields retryable.
    service = TaskService(ControlledResearch(), root)
    assert service.get(record["id"]).retry_available is False
    service._persist()
    client, research, _, _ = api_factory(artifact_root=root)
    disk_before = (root / ".research-tasks.json").read_bytes()
    response = await client.post(f"/api/research/{record['id']}/retry")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "retry_unavailable"
    assert (root / ".research-tasks.json").read_bytes() == disk_before
    assert research.calls == []


async def test_retry_returns_404_when_original_knowledge_base_was_deleted(api_factory):
    research = ControlledResearch({0: TimeoutError("failed")})
    client, _, root, store = api_factory(research)
    kb = store.create_knowledge_base("original knowledge base")
    task_id = await submit(client, knowledge_base_ids=[kb.id], source_mode="hybrid")
    await research.wait_started(0)
    research.releases[0].set()
    await wait_status(client, task_id, "failed")
    disk_before = (root / ".research-tasks.json").read_bytes()
    with sqlite3.connect(store.database) as connection:
        connection.execute("DELETE FROM knowledge_base WHERE id = ?", (kb.id,))
    response = await client.post(f"/api/research/{task_id}/retry")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "knowledge_base_not_found"
    assert (root / ".research-tasks.json").read_bytes() == disk_before
    assert len(research.calls) == 1


@pytest.mark.parametrize("use_defaults", [False, True])
async def test_request_parameters_and_retry_of_round_trip_after_restart(services, use_defaults):
    service = services()
    options = {} if use_defaults else dict(
        requirements=EvidenceRequirement("saved", ("claim one", "claim two"),
                                         ("external_web", "local_import"), 3, True),
        as_of=datetime.fromisoformat("2026-10-30T12:34:56+08:00"), max_deep_calls=0,
        output_language="English", research_depth="high", claims_source="query_fallback",
        source_mode="hybrid")
    task = service.create("saved question", [] if use_defaults else ["kb-one", "kb-two"],
                          retry_of="b" * 32, **options)
    await service.research.wait_started(0)
    service.research.releases[0].set()
    await service._background_tasks[task.id]
    restored = TaskService(ControlledResearch(), service.root).get(task.id)
    assert asdict(restored) == asdict(task)
    assert records(service.root)[task.id]["as_of"] == task.as_of
    assert restored.retry_of == "b" * 32
    assert restored.retry_available is True


@pytest.mark.parametrize("status", ["queued", "running", "cancelled"])
def test_restart_interrupts_active_tasks_but_keeps_cancelled_terminal(tmp_path, status):
    error = {"code": "research_cancelled", "message": "Research task was cancelled"} if status == "cancelled" else None
    record = full_record(status=status, phase=status, error=error,
                         completed_at="2026-10-30T14:00:00+08:00" if error else None)
    write_record(tmp_path, record)
    task = TaskService(ControlledResearch(), tmp_path).get(record["id"])
    if status == "cancelled":
        assert task.status == task.phase == "cancelled"
        assert asdict(task) == record
    else:
        assert task.status == task.phase == "failed"
        assert task.error.code == "research_interrupted"
        assert task.completed_at is not None
        assert task.completed_at == task.updated_at
    assert records(tmp_path)[task.id]["status"] == task.status
