import asyncio
import json
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deepresearch_kb.api import create_app
from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.local_control import (
    AllowedRoot, CloudClient, LocalConfigStore, LocalControlError, LocalControlService,
    create_local_app)
from deepresearch_kb.services.research import ResearchService
from deepresearch_kb.services.tasks import TaskService
from tests.deepresearch_kb.auth_support import configured_auth


async def loader(path):
    return [{"raw_content": path.read_text(encoding="utf-8")}]


def stage4_clients(tmp_path):
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    cloud_store = KnowledgeStore(tmp_path / "cloud.sqlite", loader=loader)
    cloud_kb = cloud_store.create_knowledge_base("Cloud authority")
    auth = configured_auth(cloud_store.database)
    raw_token = auth.issue_cli_token("local control").token
    cloud_app = create_app(
        store=cloud_store, auth=auth, artifact_root=tmp_path / "tasks",
        backup_root=tmp_path / "cloud-backups")
    cloud_http = TestClient(cloud_app)
    cloud = CloudClient("http://cloud.test", raw_token, client=cloud_http)
    local_store = KnowledgeStore(tmp_path / "local.sqlite", loader=loader)
    local_kb = local_store.create_knowledge_base("Optional local validation")
    service = LocalControlService(AllowedRoot(allowed_dir), cloud, local_store)
    local_app = create_local_app(
        root=allowed_dir, server="http://cloud.test", token=raw_token,
        service=service, allowed_hosts={"testserver", "testclient"},
        control_token="stage4-control-token")
    return (
        TestClient(local_app), cloud_store, cloud_kb.id, local_kb.id,
        allowed_dir, raw_token)


def mutate(client, path, payload=None):
    return client.post(
        path, json=payload,
        headers={"X-Local-Control-Token": "stage4-control-token"})


def test_allowed_root_rejects_traversal_absolute_and_outside_symlink(tmp_path):
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (allowed_dir / "escape").symlink_to(outside, target_is_directory=True)
    allowed = AllowedRoot(allowed_dir)

    for unsafe in ("../outside", str(outside), "escape"):
        with pytest.raises(LocalControlError) as exc_info:
            allowed.directory(unsafe)
        assert exc_info.value.code == "path_outside_allowed_root"


def test_local_api_enforces_loopback_csrf_and_safe_scan(tmp_path):
    client, _, _, _, root, cloud_token = stage4_clients(tmp_path)
    (root / "docs").mkdir()
    (root / "docs" / "a.md").write_text("alpha", encoding="utf-8")
    (root / "docs" / "skip.bin").write_bytes(b"ignored")
    (root / ".git").mkdir()
    (root / ".git" / "secret.md").write_text("ignored", encoding="utf-8")

    page = client.get("/")
    assert page.status_code == 200
    assert cloud_token not in page.text
    assert client.get("/api/local/status").json()["authoritative_store"] == "local"
    assert client.post("/api/local/scan", json={"directory": "docs"}).status_code == 403
    rejected_host = client.get(
        "/api/local/status", headers={"host": "attacker.example"})
    assert rejected_host.status_code == 403

    scanned = mutate(client, "/api/local/scan", {"directory": "."})
    assert scanned.status_code == 200
    assert [item["logical_path"] for item in scanned.json()["files"]] == ["docs/a.md"]
    traversal = mutate(client, "/api/local/scan", {"directory": "../"})
    assert traversal.status_code == 400
    assert traversal.json()["detail"]["code"] == "path_outside_allowed_root"


def test_push_is_authenticated_idempotent_and_creates_new_version(tmp_path):
    client, cloud_store, cloud_kb, _, root, _ = stage4_clients(tmp_path)
    docs = root / "docs"
    docs.mkdir()
    source = docs / "a.md"
    source.write_text("version one", encoding="utf-8")

    first = mutate(client, "/api/local/push", {
        "directory": "docs", "kb_id": cloud_kb})
    second = mutate(client, "/api/local/push", {
        "directory": "docs", "kb_id": cloud_kb})
    assert first.json() | {"errors": []} == {
        "imported": 1, "unchanged": 0, "failed": 0, "skipped": 0,
        "errors": []}
    assert second.json()["unchanged"] == 1
    assert len(cloud_store.list_versions(cloud_kb, "a.md")) == 1

    source.write_text("version two", encoding="utf-8")
    changed = mutate(client, "/api/local/push", {
        "directory": "docs", "kb_id": cloud_kb})
    assert changed.json()["imported"] == 1
    versions = cloud_store.list_versions(cloud_kb, "a.md")
    assert [item.version for item in versions] == [1, 2]
    assert [item.status for item in versions] == ["superseded", "active"]


def test_optional_local_ingest_and_cloud_backup_download(tmp_path):
    client, _, _, local_kb, root, _ = stage4_clients(tmp_path)
    (root / "note.txt").write_text("local validation", encoding="utf-8")

    ingested = mutate(client, "/api/local/ingest", {
        "directory": ".", "kb_id": local_kb})
    assert ingested.status_code == 200
    assert ingested.json()["imported"] == 1

    downloaded = mutate(client, "/api/local/backups")
    assert downloaded.status_code == 200
    relative = downloaded.json()["relative_path"]
    assert relative.startswith(".deepresearch-kb/backups/kb-")
    backup = root / relative
    assert backup.is_file()
    with sqlite3.connect(backup) as database:
        assert database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not list(backup.parent.glob(".download-*.tmp"))


def test_cloud_errors_are_structured_and_do_not_expose_token(tmp_path):
    client, _, _, _, _, cloud_token = stage4_clients(tmp_path)
    response = mutate(client, "/api/local/push", {
        "directory": ".", "kb_id": "missing"})
    body = response.json()
    assert cloud_token not in response.text
    assert body == {
        "imported": 0, "unchanged": 0, "failed": 0,
        "skipped": 0, "errors": []}


def test_local_research_works_without_cloud_configuration(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    store = KnowledgeStore(tmp_path / "local.sqlite", loader=loader)
    kb = store.create_knowledge_base("Local only")

    observed = {}

    class LocalEngine:
        async def run(self, query, *, knowledge_base_ids, requirements, output_dir,
                      as_of=None, max_deep_calls=1):
            observed.update({
                "query": query,
                "knowledge_base_ids": knowledge_base_ids,
                "requirements": requirements,
                "as_of": as_of,
                "max_deep_calls": max_deep_calls,
            })
            output_dir.mkdir(parents=True, exist_ok=False)
            (output_dir / "report.md").write_text(f"# {query}", encoding="utf-8")
            for name, value in (("sources.json", []), ("trace.json", []),
                                ("run.json", {"status": "completed"})):
                (output_dir / name).write_text(json.dumps(value), encoding="utf-8")
            return {"metrics": {"status": "completed"}}

    service = LocalControlService(
        AllowedRoot(root), CloudClient(None, None), store,
        TaskService(ResearchService(LocalEngine()), tmp_path / "tasks"))
    app = create_local_app(
        root=root, server=None, token=None, service=service,
        allowed_hosts={"testserver", "testclient"}, control_token="local-only-token")
    client = TestClient(app)
    response = client.post(
        "/api/local/research",
        json={
            "query": "本地问题", "knowledge_base_ids": [kb.id],
            "required_claims": ["回答本地事实"],
            "required_source_types": ["local_import"],
            "minimum_distinct_sources": 2,
            "require_current_version": True,
            "as_of": "2026-09-15T12:00:00+08:00",
            "max_deep_calls": 3,
        },
        headers={"X-Local-Control-Token": "local-only-token"})
    assert response.status_code == 200
    task_id = response.json()["task_id"]
    for _ in range(20):
        status = client.get(f"/api/local/research/{task_id}").json()
        if status["status"] == "completed":
            break
        asyncio.run(asyncio.sleep(0.01))
    assert status["status"] == "completed"
    assert client.get(f"/api/local/research/{task_id}/report").text == "# 本地问题"
    assert client.get(f"/api/local/research/{task_id}/sources").json() == []
    assert client.get(f"/api/local/research/{task_id}/trace").json() == []
    assert client.get(f"/api/local/research/{task_id}/metrics").json() == {
        "status": "completed"}
    assert observed["knowledge_base_ids"] == (kb.id,)
    requirement = observed["requirements"]
    assert requirement.required_claims == ("回答本地事实",)
    assert requirement.required_source_types == ("local_import",)
    assert requirement.minimum_distinct_sources == 2
    assert requirement.require_current_version is True
    assert observed["as_of"].isoformat() == "2026-09-15T12:00:00+08:00"
    assert observed["max_deep_calls"] == 3

    invalid_kb = client.post(
        "/api/local/research",
        json={"query": "本地问题", "knowledge_base_ids": ["missing"]},
        headers={"X-Local-Control-Token": "local-only-token"})
    assert invalid_kb.status_code == 404
    assert invalid_kb.json()["detail"]["code"] == "local_knowledge_base_not_found"


def test_explicit_pull_imports_cloud_latest_version_to_local(tmp_path):
    client, cloud_store, cloud_kb, local_kb, root, _ = stage4_clients(tmp_path)
    source = root / "remote.md"
    source.write_text("cloud v1", encoding="utf-8")
    asyncio.run(cloud_store.ingest(
        cloud_kb, source, logical_path="docs/remote.md",
        source_type="web_upload", source_uri="upload://remote"))

    pulled = mutate(client, "/api/local/pull", {
        "cloud_kb_id": cloud_kb, "local_kb_id": local_kb})
    assert pulled.status_code == 200
    assert pulled.json()["imported"] == 1

    local_database = client.get("/api/local/status").json()["local_database"]
    local_store = KnowledgeStore(local_database, loader=loader)
    versions = local_store.list_versions(local_kb, "docs/remote.md")
    assert len(versions) == 1
    assert versions[0].source_type == "web_upload"
    assert versions[0].source_uri.startswith("cloud://")

    unchanged = mutate(client, "/api/local/pull", {
        "cloud_kb_id": cloud_kb, "local_kb_id": local_kb})
    assert unchanged.json()["unchanged"] == 1


def test_pull_reports_conflict_without_overwriting_local_version(tmp_path):
    client, cloud_store, cloud_kb, local_kb, root, _ = stage4_clients(tmp_path)
    cloud_source = root / "cloud.md"
    cloud_source.write_text("cloud content", encoding="utf-8")
    asyncio.run(cloud_store.ingest(
        cloud_kb, cloud_source, logical_path="shared.md",
        source_type="web_upload", source_uri="upload://shared"))
    local_database = client.get("/api/local/status").json()["local_database"]
    local_store = KnowledgeStore(local_database, loader=loader)
    local_source = root / "local.md"
    local_source.write_text("local content", encoding="utf-8")
    asyncio.run(local_store.ingest(
        local_kb, local_source, logical_path="shared.md",
        source_type="local_import"))

    result = mutate(client, "/api/local/pull", {
        "cloud_kb_id": cloud_kb, "local_kb_id": local_kb}).json()
    assert result["conflicts"] == 1
    assert result["imported"] == 0
    assert result["conflict_items"][0]["logical_path"] == "shared.md"
    versions = local_store.list_versions(local_kb, "shared.md")
    assert len(versions) == 1
    assert versions[0].source_uri.startswith("file:")


def test_explicit_kb_push_tracks_baseline_and_adds_cloud_versions(tmp_path):
    client, cloud_store, cloud_kb, local_kb, root, _ = stage4_clients(tmp_path)
    local_store = KnowledgeStore(
        client.get("/api/local/status").json()["local_database"], loader=loader)
    source = root / "local.md"
    source.write_text("local v1", encoding="utf-8")
    asyncio.run(local_store.ingest(
        local_kb, source, logical_path="docs/local.md", source_type="local_import"))

    first = mutate(client, "/api/local/sync/push", {
        "cloud_kb_id": cloud_kb, "local_kb_id": local_kb}).json()
    assert first["imported"] == 1
    assert len(cloud_store.list_versions(cloud_kb, "docs/local.md")) == 1

    source.write_text("local v2", encoding="utf-8")
    asyncio.run(local_store.ingest(
        local_kb, source, logical_path="docs/local.md", source_type="local_import"))
    second = mutate(client, "/api/local/sync/push", {
        "cloud_kb_id": cloud_kb, "local_kb_id": local_kb}).json()
    assert second["imported"] == 1
    assert [item.version for item in cloud_store.list_versions(
        cloud_kb, "docs/local.md")] == [1, 2]

    unchanged = mutate(client, "/api/local/sync/push", {
        "cloud_kb_id": cloud_kb, "local_kb_id": local_kb}).json()
    assert unchanged["unchanged"] == 1


def test_explicit_kb_push_reports_divergence_without_overwriting_cloud(tmp_path):
    client, cloud_store, cloud_kb, local_kb, root, _ = stage4_clients(tmp_path)
    local_store = KnowledgeStore(
        client.get("/api/local/status").json()["local_database"], loader=loader)
    local_source = root / "local.md"
    local_source.write_text("shared v1", encoding="utf-8")
    asyncio.run(local_store.ingest(
        local_kb, local_source, logical_path="shared.md", source_type="local_import"))
    mutate(client, "/api/local/sync/push", {
        "cloud_kb_id": cloud_kb, "local_kb_id": local_kb})

    local_source.write_text("local v2", encoding="utf-8")
    asyncio.run(local_store.ingest(
        local_kb, local_source, logical_path="shared.md", source_type="local_import"))
    cloud_source = root / "cloud.md"
    cloud_source.write_text("cloud v2", encoding="utf-8")
    asyncio.run(cloud_store.ingest(
        cloud_kb, cloud_source, logical_path="shared.md", source_type="web_upload",
        source_uri="upload://shared.md"))
    cloud_hash = cloud_store.list_versions(cloud_kb, "shared.md")[-1].content_hash

    result = mutate(client, "/api/local/sync/push", {
        "cloud_kb_id": cloud_kb, "local_kb_id": local_kb}).json()
    assert result["conflicts"] == 1
    assert result["imported"] == 0
    assert result["conflict_items"][0]["reason"] == "local_and_cloud_versions_differ"
    assert cloud_store.list_versions(cloud_kb, "shared.md")[-1].content_hash == cloud_hash


def test_local_kb_create_and_restricted_cloud_config_storage(tmp_path):
    client, _, _, _, _, _ = stage4_clients(tmp_path)
    created = client.post(
        "/api/local/kbs", json={"name": "Created locally"},
        headers={"X-Local-Control-Token": "stage4-control-token"})
    assert created.status_code == 200
    assert created.json()["name"] == "Created locally"
    assert any(item["id"] == created.json()["id"]
               for item in client.get("/api/local/kbs").json())

    config = LocalConfigStore(tmp_path / "private" / "cloud.json")
    config.save("https://research.example.com", "drkb_secret")
    assert config.load() == ("https://research.example.com", "drkb_secret")
    if os.name != "nt":
        assert config.path.stat().st_mode & 0o777 == 0o600
    config.clear()
    assert config.load() == (None, None)
