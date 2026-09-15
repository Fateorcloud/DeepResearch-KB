import asyncio

from fastapi.testclient import TestClient

from deepresearch_kb.api import create_app
from deepresearch_kb.knowledge import KnowledgeStore
from tests.deepresearch_kb.auth_support import bearer_client, configured_auth


async def loader(path):
    return [{"raw_content": path.read_text()}]


def test_kb_rename_preview_and_version_detail(tmp_path):
    store = KnowledgeStore(tmp_path / "kb.sqlite", loader=loader)
    kb = store.create_knowledge_base("Before")
    created_at = kb.created_at
    source = tmp_path / "decision.md"
    source.write_text("old decision")
    first = asyncio.run(store.ingest(
        kb.id, source, logical_path="architecture/decision.md",
        source_uri="file:///original/decision.md"))
    source.write_text("current decision " + "x" * 4100)
    second = asyncio.run(store.ingest(
        kb.id, source, logical_path="architecture/decision.md",
        source_uri="file:///original/decision.md"))

    auth = configured_auth(store.database)
    client = bearer_client(create_app(
        store=store, auth=auth, artifact_root=tmp_path / "tasks"), auth)
    renamed = client.patch(f"/api/kbs/{kb.id}", json={"name": "  After  "})
    assert renamed.status_code == 200
    assert renamed.json() == {"id": kb.id, "name": "After", "created_at": created_at}
    assert client.get("/api/kbs").json()[0]["id"] == kb.id
    assert client.get("/api/kbs").json()[0]["name"] == "After"

    detail = client.get(f"/api/kbs/{kb.id}/documents/{first.document_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["document_id"] == first.document_id
    assert payload["current_version"] == second.version == 2
    assert payload["version_count"] == 2
    assert payload["parsed_content_preview"].startswith("current decision")
    assert "old decision" not in payload["parsed_content_preview"]
    assert len(payload["parsed_content_preview"]) == 4000
    assert payload["preview_truncated"] is True
    assert payload["source_uri"] == "file:///original/decision.md"

    old = client.get(
        f"/api/kbs/{kb.id}/documents/{first.document_id}/versions/1")
    current = client.get(
        f"/api/kbs/{kb.id}/documents/{first.document_id}/versions/2")
    assert old.status_code == current.status_code == 200
    assert old.json()["parsed_content"] == "old decision"
    assert old.json()["status"] == "superseded"
    assert current.json()["parsed_content"].startswith("current decision")
    assert current.json()["status"] == "active"
    assert current.json()["content_hash"] == second.content_hash
    assert current.json()["updated_at"] == second.updated_at
    assert current.json()["ingested_at"] == second.ingested_at


def test_stage1_contract_returns_structured_not_found_and_validation_errors(tmp_path):
    store = KnowledgeStore(tmp_path / "kb.sqlite", loader=loader)
    kb = store.create_knowledge_base("KB")
    auth = configured_auth(store.database)
    client = bearer_client(create_app(
        store=store, auth=auth, artifact_root=tmp_path / "tasks"), auth)

    invalid_name = client.patch(f"/api/kbs/{kb.id}", json={"name": " "})
    assert invalid_name.status_code == 422
    assert invalid_name.json()["detail"]["code"] == "invalid_request"

    missing_kb = client.patch("/api/kbs/missing", json={"name": "New"})
    assert missing_kb.status_code == 404
    assert missing_kb.json()["detail"]["code"] == "knowledge_base_not_found"

    missing_doc = client.get(f"/api/kbs/{kb.id}/documents/missing")
    assert missing_doc.status_code == 404
    assert missing_doc.json()["detail"]["code"] == "document_not_found"

    missing_version = client.get(
        f"/api/kbs/{kb.id}/documents/missing/versions/1")
    assert missing_version.status_code == 404
    assert missing_version.json()["detail"]["code"] == "document_version_not_found"
