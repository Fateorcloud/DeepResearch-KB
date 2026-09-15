"""Local-only Stage 4 browser acceptance servers."""

import argparse
import asyncio
import json
import threading
from pathlib import Path

import uvicorn

from deepresearch_kb.api import create_app
from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.local_control import (
    AllowedRoot, CloudClient, LocalControlService, create_local_app)
from deepresearch_kb.services.auth import AuthService, hash_password
from deepresearch_kb.services.research import ResearchService
from deepresearch_kb.services.tasks import TaskService


async def loader(path):
    return [{"raw_content": path.read_text(encoding="utf-8")}]


class BrowserResearchEngine:
    async def run(self, query, *, knowledge_base_ids, requirements, output_dir,
                  as_of=None, max_deep_calls=1):
        await asyncio.sleep(0.15)
        output_dir.mkdir(parents=True, exist_ok=False)
        report = f"# Local-first Research\n\n{query}\n\n本地知识库 Research 已完成。"
        (output_dir / "report.md").write_text(report, encoding="utf-8")
        (output_dir / "sources.json").write_text("[]", encoding="utf-8")
        (output_dir / "trace.json").write_text("[]", encoding="utf-8")
        metrics = {"status": "completed", "max_deep_calls": max_deep_calls}
        (output_dir / "run.json").write_text(json.dumps(metrics), encoding="utf-8")
        return {"report": report, "sources": [], "trace": [], "metrics": metrics}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--cloud-port", type=int, default=8001)
    parser.add_argument("--local-port", type=int, default=8766)
    args = parser.parse_args()
    base = Path(args.root).resolve()
    local_root = base / "allowed"
    local_root.mkdir(parents=True, exist_ok=True)
    (local_root / "docs").mkdir(exist_ok=True)
    (local_root / "docs" / "browser.md").write_text(
        "Stage 4 local control browser acceptance.", encoding="utf-8")
    cloud_store = KnowledgeStore(base / "cloud.sqlite", loader=loader)
    kb = cloud_store.create_knowledge_base("Stage 4 Cloud KB")
    auth = AuthService(
        cloud_store.database, username="admin", password_hash=hash_password("stage4-browser-test"),
        session_secret="stage4-browser-test-session-secret-32-bytes-minimum")
    token = auth.issue_cli_token("stage4 browser").token
    cloud_app = create_app(
        store=cloud_store, auth=auth, artifact_root=base / "tasks",
        backup_root=base / "backups")
    local_store = KnowledgeStore(base / "local.sqlite", loader=loader)
    local_kb = local_store.create_knowledge_base("Stage 4 Local KB")
    asyncio.run(local_store.ingest(
        local_kb.id, local_root / "docs" / "browser.md",
        logical_path="docs/browser.md", source_type="local_import"))
    service = LocalControlService(
        AllowedRoot(local_root), CloudClient(None, None), local_store,
        TaskService(ResearchService(BrowserResearchEngine()), base / "local-tasks"))
    local_app = create_local_app(
        root=local_root, server=None, token=None, service=service,
        allowed_hosts={"127.0.0.1", "localhost"})
    print(f"Stage 4 browser KB: {kb.id}", flush=True)
    print(f"Stage 4 local KB: {local_kb.id}", flush=True)
    print(f"Stage 4 browser token: {token}", flush=True)
    print(f"Stage 4 browser root: {local_root}", flush=True)
    cloud = uvicorn.Server(uvicorn.Config(
        cloud_app, host="127.0.0.1", port=args.cloud_port, log_level="warning"))
    thread = threading.Thread(target=cloud.run, daemon=True)
    thread.start()
    uvicorn.run(local_app, host="127.0.0.1", port=args.local_port, log_level="warning")


if __name__ == "__main__":
    main()
