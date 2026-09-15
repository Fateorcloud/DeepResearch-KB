import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from deepresearch_kb.api import create_app
from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.local_control import (
    AllowedRoot, CloudClient, LocalControlError, LocalControlService,
    create_local_app)
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
