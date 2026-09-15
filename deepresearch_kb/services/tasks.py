import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..sufficiency import EvidenceRequirement


def _now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskError:
    code: str
    message: str


@dataclass
class ResearchTask:
    id: str
    query: str
    status: str = "queued"
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    error: TaskError | None = None
    artifact_path: str | None = None


class TaskService:
    def __init__(self, research, root):
        self.research = research
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.tasks = {}

    def create(self, query, knowledge_base_ids, *, requirements=None,
               as_of=None, max_deep_calls=1):
        if requirements is None:
            # Keep the existing query-only MCP contract usable while ensuring
            # ResearchEngine never receives an implicit None requirement.
            requirements = EvidenceRequirement("task-query", (query,))
        task = ResearchTask(uuid.uuid4().hex, query, created_at=_now())
        self.tasks[task.id] = task
        asyncio.create_task(self._run(task, tuple(knowledge_base_ids), requirements,
                                      as_of, max_deep_calls))
        return task

    async def _run(self, task, knowledge_base_ids, requirements, as_of,
                   max_deep_calls):
        task.status, task.started_at = "running", _now()
        folder = self.root / task.id
        task.artifact_path = str(folder)
        try:
            result = await self.research.run(
                task.query, knowledge_base_ids=knowledge_base_ids,
                requirements=requirements, output_dir=folder,
                as_of=as_of, max_deep_calls=max_deep_calls)
            if result.get("metrics", {}).get("status") == "failed":
                raise RuntimeError("research engine reported failure")
            task.status = "completed"
        except Exception:
            task.status = "failed"
            task.error = TaskError("research_failed", "Research task failed")
        task.completed_at = _now()

    def get(self, task_id):
        if task_id not in self.tasks:
            raise KeyError(task_id)
        return self.tasks[task_id]

    def list(self):
        return sorted(self.tasks.values(), key=lambda task: task.created_at, reverse=True)
