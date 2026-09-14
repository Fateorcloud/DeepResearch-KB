"""Minimal standalone FastAPI application for DeepResearch-KB."""
import asyncio
import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .knowledge import KnowledgeStore
from .services.knowledge import KnowledgeService
from .services.research import ResearchService
from .services.tasks import TaskService
from .directory import SUPPORTED


class KBCreate(BaseModel):
    name: str


class ResearchCreate(BaseModel):
    query: str
    knowledge_base_ids: list[str]


def create_app(database="data/kb.sqlite", artifact_root="data/tasks", *, store=None, research=None):
    store = store or KnowledgeStore(database)
    knowledge = KnowledgeService(store)
    tasks = TaskService(research, artifact_root) if research else None
    app = FastAPI(title="DeepResearch-KB API")

    @app.post("/api/kbs")
    def create_kb(body: KBCreate):
        try: return asdict(knowledge.create(body.name))
        except ValueError as exc: raise HTTPException(400, detail=str(exc))

    @app.get("/api/kbs")
    def list_kbs(): return [asdict(kb) for kb in knowledge.list()]

    @app.post("/api/kbs/{kb_id}/documents")
    async def upload(kb_id: str, file: UploadFile = File(...), logical_path: str = Form(...)):
        if not file.filename or Path(file.filename).name != file.filename:
            raise HTTPException(400, detail="invalid filename")
        if Path(logical_path).suffix.lower() not in SUPPORTED:
            raise HTTPException(400, detail="unsupported extension")
        if not logical_path.strip() or logical_path.replace("\\", "/").startswith("/") or ".." in Path(logical_path).parts:
            raise HTTPException(400, detail="invalid logical_path")
        data = await file.read()
        if not data: raise HTTPException(400, detail="empty file")
        with tempfile.NamedTemporaryFile(prefix="drkb-upload-", suffix=Path(logical_path).suffix, delete=False) as tmp:
            tmp.write(data); staged = Path(tmp.name)
        try:
            version = await knowledge.ingest(kb_id, staged, logical_path=logical_path,
                                             source_type="web_upload", source_uri=f"upload://{kb_id}/{logical_path}")
            return asdict(version)
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(400 if not isinstance(exc, KeyError) else 404, detail=str(exc))
        finally: staged.unlink(missing_ok=True)

    @app.get("/api/kbs/{kb_id}/documents")
    def documents(kb_id):
        try: return knowledge.documents(kb_id)
        except KeyError: raise HTTPException(404, detail="unknown knowledge base")

    @app.get("/api/kbs/{kb_id}/documents/{document_id}/versions")
    def versions(kb_id, document_id):
        try: return [asdict(v) for v in knowledge.versions(kb_id, document_id)]
        except KeyError: raise HTTPException(404, detail="unknown document")

    @app.post("/api/research")
    def create_research(body: ResearchCreate):
        if tasks is None: raise HTTPException(503, detail="research service unavailable")
        task = tasks.create(body.query, body.knowledge_base_ids)
        return {"task_id": task.id}

    @app.get("/api/research/{task_id}")
    def status(task_id):
        try: return asdict(tasks.get(task_id))
        except KeyError: raise HTTPException(404, detail="unknown task")

    def artifact(task_id, name):
        try: task = tasks.get(task_id)
        except KeyError: raise HTTPException(404, detail="unknown task")
        if task.status != "completed": raise HTTPException(409, detail="task not completed")
        path = Path(task.artifact_path) / name
        if not path.exists(): raise HTTPException(404, detail="artifact unavailable")
        return json.loads(path.read_text()) if path.suffix == ".json" else path.read_text()

    for name in ("sources", "trace", "run"):
        app.get(f"/api/research/{{task_id}}/{name}")(lambda task_id, n=name: artifact(task_id, f"{n}.json"))
    app.get("/api/research/{task_id}/report")(lambda task_id: artifact(task_id, "report.md"))
    return app


app = create_app()
