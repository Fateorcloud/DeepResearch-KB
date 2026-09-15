"""Local-only Stage 4 browser acceptance servers."""

import argparse
import threading
from pathlib import Path

import uvicorn

from deepresearch_kb.api import create_app
from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.local_control import create_local_app
from deepresearch_kb.services.auth import AuthService, hash_password


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
    cloud_store = KnowledgeStore(base / "cloud.sqlite")
    kb = cloud_store.create_knowledge_base("Stage 4 Cloud KB")
    auth = AuthService(
        cloud_store.database, username="admin", password_hash=hash_password("stage4-browser-test"),
        session_secret="stage4-browser-test-session-secret-32-bytes-minimum")
    token = auth.issue_cli_token("stage4 browser").token
    cloud_app = create_app(
        store=cloud_store, auth=auth, artifact_root=base / "tasks",
        backup_root=base / "backups")
    local_app = create_local_app(
        root=local_root, server=f"http://127.0.0.1:{args.cloud_port}", token=token,
        database=base / "local.sqlite", allowed_hosts={"127.0.0.1", "localhost"})
    print(f"Stage 4 browser KB: {kb.id}", flush=True)
    print(f"Stage 4 browser root: {local_root}", flush=True)
    cloud = uvicorn.Server(uvicorn.Config(
        cloud_app, host="127.0.0.1", port=args.cloud_port, log_level="warning"))
    thread = threading.Thread(target=cloud.run, daemon=True)
    thread.start()
    uvicorn.run(local_app, host="127.0.0.1", port=args.local_port, log_level="warning")


if __name__ == "__main__":
    main()
