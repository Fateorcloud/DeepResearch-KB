"""Local-only Stage 3 browser acceptance server with deterministic research output."""

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

import uvicorn

from deepresearch_kb.api import create_app
from deepresearch_kb.knowledge import KnowledgeStore
from deepresearch_kb.models import Evidence
from deepresearch_kb.services.auth import AuthService, hash_password


USERNAME = "admin"
PASSWORD = "stage3-browser-test"
SESSION_SECRET = "stage3-browser-test-session-secret-32-bytes-minimum"


async def loader(path):
    return [{"raw_content": path.read_text(encoding="utf-8")}]


class BrowserAcceptanceEngine:
    async def run(self, query, *, knowledge_base_ids, requirements, output_dir,
                  as_of=None, max_deep_calls=1):
        await asyncio.sleep(0.15)
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=False)
        evidence = Evidence(
            "browser-evidence", "Stage 3 browser acceptance evidence.",
            "web_upload", "upload://browser/acceptance.txt",
            "acceptance.txt", "browser-document", 1, 1.0,
            knowledge_base_ids[0] if knowledge_base_ids else None,
            status="active")
        sources = [asdict(evidence)]
        trace = [{
            "question": query,
            "source_policy": "internal",
            "rationale": "browser acceptance fixture through the engine interface",
            "requirement": asdict(requirements),
            "decisions": [{
                "route": "stop", "reason": "acceptance evidence satisfied",
                "terminal_status": "sufficient"}],
            "final_route": "stop",
        }]
        metrics = {
            "status": "completed",
            "planning_source": "browser_acceptance_fixture",
            "requirement_origin": "caller_task_requirement_broadcast_unchanged",
            "final_route_summary": ["stop"],
            "quick_calls": 0,
            "deep_calls": 0,
            "max_deep_calls": max_deep_calls,
            "latency_seconds": 0.15,
            "llm_calls_completed": 0,
            "llm_tokens": None,
            "actual_cost_usd": None,
        }
        report = """# Stage 3 Browser Acceptance

The authenticated Web flow completed successfully using uploaded knowledge.

## Evidence

- The task passed through FastAPI, TaskService, ResearchService, and the ResearchEngine interface.
- Report, sources, trace, and metrics are available as separate artifacts.
"""
        (root / "report.md").write_text(report, encoding="utf-8")
        (root / "sources.json").write_text(json.dumps(sources), encoding="utf-8")
        (root / "trace.json").write_text(json.dumps(trace), encoding="utf-8")
        (root / "run.json").write_text(json.dumps(metrics), encoding="utf-8")
        return {"report": report, "sources": [evidence], "trace": trace, "metrics": metrics}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    store = KnowledgeStore(root / "kb.sqlite", loader=loader)
    auth = AuthService(
        store.database, username=USERNAME, password_hash=hash_password(PASSWORD),
        session_secret=SESSION_SECRET)
    app = create_app(
        store=store, engine=BrowserAcceptanceEngine(), auth=auth,
        artifact_root=root / "tasks", backup_root=root / "backups")
    print(f"Stage 3 acceptance login: {USERNAME} / {PASSWORD}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
