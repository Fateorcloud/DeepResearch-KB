import asyncio
import io
import json
import sqlite3
import zipfile
from fastapi.testclient import TestClient

from deepresearch_kb.api import create_app
from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.services.auth import hash_password
from tests.deepresearch_kb.auth_support import (
    TEST_PASSWORD, bearer_client, configured_auth)


async def loader(path):
    return [{"raw_content": path.read_text()}]


def _login(client):
    response = client.post("/api/auth/login", json={
        "username": "admin", "password": TEST_PASSWORD})
    assert response.status_code == 200
    return response.json()["csrf_token"], response


def test_unconfigured_auth_fails_closed_except_health_and_login(tmp_path, monkeypatch):
    for name in ("DRKB_ADMIN_USERNAME", "DRKB_ADMIN_PASSWORD_HASH",
                 "DRKB_SESSION_SECRET"):
        monkeypatch.delenv(name, raising=False)
    app = create_app(
        database=tmp_path / "kb.sqlite", artifact_root=tmp_path / "tasks",
        backup_root=tmp_path / "backups")
    client = TestClient(app, base_url="https://testserver")

    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/kbs").status_code == 503
    assert client.get("/api/kbs").json()["detail"]["code"] == "auth_not_configured"
    assert client.get("/openapi.json").status_code == 503
    login = client.post("/api/auth/login", json={"username": "admin", "password": "x"})
    assert login.status_code == 503
    assert login.json()["detail"]["code"] == "auth_not_configured"


def test_browser_session_cookie_csrf_logout_and_uniform_login_failure(tmp_path):
    store = KnowledgeStore(tmp_path / "kb.sqlite")
    auth = configured_auth(store.database)
    app = create_app(store=store, auth=auth, artifact_root=tmp_path / "tasks",
                     backup_root=tmp_path / "backups")
    client = TestClient(app, base_url="https://testserver")

    assert client.get("/api/kbs").status_code == 401
    wrong_user = client.post("/api/auth/login", json={
        "username": "someone", "password": "wrong"})
    wrong_password = client.post("/api/auth/login", json={
        "username": "admin", "password": "wrong"})
    assert wrong_user.status_code == wrong_password.status_code == 401
    assert wrong_user.json() == wrong_password.json()

    csrf, login = _login(client)
    cookie = login.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert client.get("/api/auth/session").json() == {
        "username": "admin", "auth_kind": "session", "csrf_token": csrf}

    assert client.post("/api/kbs", json={"name": "No CSRF"}).status_code == 403
    assert client.post("/api/kbs", json={"name": "Bad CSRF"},
                       headers={"X-CSRF-Token": "wrong"}).status_code == 403
    created = client.post("/api/kbs", json={"name": "Session KB"},
                          headers={"X-CSRF-Token": csrf})
    assert created.status_code == 200

    logout = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert logout.status_code == 200
    assert client.get("/api/auth/session").status_code == 401


def test_login_rate_limit_and_argon2_password_hash(tmp_path):
    assert hash_password("a password").startswith("$argon2")
    store = KnowledgeStore(tmp_path / "kb.sqlite")
    auth = configured_auth(store.database, login_max_failures=2,
                           login_window_seconds=60)
    app = create_app(store=store, auth=auth, artifact_root=tmp_path / "tasks",
                     backup_root=tmp_path / "backups")
    client = TestClient(app, base_url="https://testserver")
    body = {"username": "admin", "password": "wrong"}

    assert client.post("/api/auth/login", json=body).status_code == 401
    assert client.post("/api/auth/login", json=body).status_code == 401
    limited = client.post("/api/auth/login", json=body)
    assert limited.status_code == 429
    assert limited.json()["detail"] == {
        "code": "login_rate_limited", "message": "Login temporarily unavailable"}


def test_cli_token_issue_list_use_rotation_and_revocation(tmp_path):
    store = KnowledgeStore(tmp_path / "kb.sqlite")
    auth = configured_auth(store.database)
    app = create_app(store=store, auth=auth, artifact_root=tmp_path / "tasks",
                     backup_root=tmp_path / "backups")
    browser = TestClient(app, base_url="https://testserver")
    csrf, _ = _login(browser)

    issued = browser.post("/api/auth/tokens", json={"label": "laptop"},
                          headers={"X-CSRF-Token": csrf})
    assert issued.status_code == 200
    token = issued.json()["token"]
    token_id = issued.json()["id"]
    assert token.startswith("drkb_")

    listed = browser.get("/api/auth/tokens").json()
    assert listed[0]["id"] == token_id
    assert listed[0]["label"] == "laptop"
    assert "token" not in listed[0] and "token_digest" not in listed[0]
    with sqlite3.connect(store.database) as db:
        stored_digest = db.execute(
            "SELECT token_digest FROM cli_token WHERE id = ?", (token_id,)).fetchone()[0]
    assert stored_digest != token and token not in stored_digest

    cli = TestClient(app, base_url="https://testserver",
                     headers={"Authorization": f"Bearer {token}"})
    assert cli.get("/api/kbs").status_code == 200
    assert cli.post("/api/kbs", json={"name": "CLI KB"}).status_code == 200
    assert cli.get("/api/auth/tokens").status_code == 403
    assert cli.get("/api/settings/status").status_code == 200

    replacement = browser.post(
        "/api/auth/tokens", json={"label": "replacement"},
        headers={"X-CSRF-Token": csrf}).json()
    assert replacement["token"] != token
    revoked = browser.delete(f"/api/auth/tokens/{token_id}",
                             headers={"X-CSRF-Token": csrf})
    assert revoked.status_code == 200
    assert cli.get("/api/kbs").status_code == 401
    replacement_client = TestClient(
        app, base_url="https://testserver",
        headers={"Authorization": f"Bearer {replacement['token']}"})
    assert replacement_client.get("/api/kbs").status_code == 200


def test_authenticated_sqlite_backup_and_complete_export(tmp_path):
    store = KnowledgeStore(tmp_path / "kb.sqlite", loader=loader)
    kb = store.create_knowledge_base("Backup KB")
    source = tmp_path / "source.txt"
    source.write_text("backup evidence")
    asyncio.run(store.ingest(kb.id, source, logical_path="source.txt"))
    task_root = tmp_path / "tasks"
    task = task_root / "task-1"
    task.mkdir(parents=True)
    (task / "report.md").write_text("report")
    backup_root = tmp_path / "backups"
    auth = configured_auth(store.database)
    app = create_app(store=store, auth=auth, artifact_root=task_root,
                     backup_root=backup_root)
    client = bearer_client(app, auth)

    created = client.post("/api/backups")
    assert created.status_code == 200
    assert set(created.json()) == {
        "backup_id", "kind", "created_at", "filename", "download_url"}
    backup_id = created.json()["backup_id"]
    download = client.get(f"/api/backups/{backup_id}")
    assert download.status_code == 200
    assert "session-secret" not in download.headers["content-disposition"]
    downloaded_db = tmp_path / "download.sqlite"
    downloaded_db.write_bytes(download.content)
    with sqlite3.connect(downloaded_db) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT COUNT(*) FROM knowledge_base").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM document_version").fetchone()[0] == 1

    exported = client.post("/api/exports")
    assert exported.status_code == 200
    archive = client.get(f"/api/exports/{exported.json()['export_id']}")
    assert archive.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
        assert {"kb.sqlite", "manifest.json", "tasks/task-1/report.md"} <= set(bundle.namelist())
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["database_counts"]["knowledge_base"] == 1
        assert manifest["database_counts"]["document_version"] == 1
        assert manifest["research_artifact_files"] == 1
        archived_db = tmp_path / "archived.sqlite"
        archived_db.write_bytes(bundle.read("kb.sqlite"))
    with sqlite3.connect(archived_db) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    assert not list(backup_root.glob("*.tmp"))
    anonymous = TestClient(app, base_url="https://testserver")
    assert anonymous.get(f"/api/backups/{backup_id}").status_code == 401
    missing = client.get("/api/backups/" + "0" * 32)
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "backup_not_found"
