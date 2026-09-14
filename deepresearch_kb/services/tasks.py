import asyncio
import json
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path


def _now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ResearchTask:
    id: str
    query: str
    status: str = "queued"
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    error_type: str | None = None
    artifact_path: str | None = None


class TaskService:
    def __init__(self, research, root):
        self.research = research
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.tasks = {}

    def create(self, query, knowledge_base_ids):
        task = ResearchTask(uuid.uuid4().hex, query, created_at=_now())
        self.tasks[task.id] = task
        asyncio.create_task(self._run(task, knowledge_base_ids))
        return task

    async def _run(self, task, knowledge_base_ids):
        task.status, task.started_at = "running", _now()
        folder = self.root / task.id
        task.artifact_path = str(folder)
        try:
            await self.research.run(task.query, knowledge_base_ids=knowledge_base_ids, output_dir=folder)
            task.status = "completed"
        except Exception as exc:
            task.status, task.error_type = "failed", type(exc).__name__
        task.completed_at = _now()

    def get(self, task_id):
        if task_id not in self.tasks:
            raise KeyError(task_id)
        return self.tasks[task_id]
