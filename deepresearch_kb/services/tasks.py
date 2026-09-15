import asyncio
import json
import os
import uuid
from dataclasses import asdict, dataclass
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
    knowledge_base_ids: tuple[str, ...] = ()
    status: str = "queued"
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    error: TaskError | None = None
    artifact_path: str | None = None
    phase: str = "queued"
    progress_percent: int = 0
    evidence_count: int = 0
    updated_at: str = ""
    output_language: str = "Chinese"
    research_depth: str = "medium"


class TaskService:
    def __init__(self, research, root):
        self.research = research
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / ".research-tasks.json"
        self.tasks = self._load()

    def _load(self):
        if not self.index_path.is_file():
            return {}
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            records = payload.get("tasks", [])
            tasks = {}
            interrupted = False
            for record in records:
                task_id = record.get("id", "")
                if len(task_id) != 32 or any(c not in "0123456789abcdef" for c in task_id):
                    continue
                error = record.get("error")
                task = ResearchTask(
                    id=task_id,
                    query=str(record.get("query", "")),
                    knowledge_base_ids=tuple(record.get("knowledge_base_ids", ())),
                    status=str(record.get("status", "failed")),
                    created_at=str(record.get("created_at", "")),
                    started_at=record.get("started_at"),
                    completed_at=record.get("completed_at"),
                    error=TaskError(**error) if isinstance(error, dict) else None,
                    artifact_path=record.get("artifact_path"),
                    phase=str(record.get("phase", record.get("status", "failed"))),
                    progress_percent=int(record.get("progress_percent", 0)),
                    evidence_count=int(record.get("evidence_count", 0)),
                    updated_at=str(record.get("updated_at", record.get("completed_at") or
                                           record.get("started_at") or record.get("created_at", ""))),
                    output_language=str(record.get("output_language", "Chinese")),
                    research_depth={"quick": "low", "standard": "medium", "deep": "high"}.get(
                        str(record.get("research_depth", "medium")),
                        str(record.get("research_depth", "medium"))),
                )
                if task.status in {"queued", "running"}:
                    task.status = "failed"
                    task.completed_at = _now()
                    task.error = TaskError(
                        "research_interrupted",
                        "Research was interrupted when Local Web stopped")
                    task.phase = "failed"
                    task.updated_at = task.completed_at
                    interrupted = True
                tasks[task.id] = task
            if interrupted:
                self.tasks = tasks
                self._persist()
            return tasks
        except (OSError, ValueError, TypeError):
            return {}

    def _persist(self):
        payload = {
            "version": 1,
            "tasks": [asdict(task) for task in self.tasks.values()],
        }
        temporary = self.index_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.index_path)

    def create(self, query, knowledge_base_ids, *, requirements=None,
               as_of=None, max_deep_calls=1, output_language="Chinese",
               research_depth="medium"):
        if requirements is None:
            # Keep the existing query-only MCP contract usable while ensuring
            # ResearchEngine never receives an implicit None requirement.
            requirements = EvidenceRequirement("task-query", (query,))
        knowledge_base_ids = tuple(knowledge_base_ids)
        created_at = _now()
        task = ResearchTask(
            uuid.uuid4().hex, query, knowledge_base_ids,
            created_at=created_at, updated_at=created_at,
            output_language=output_language, research_depth=research_depth)
        self.tasks[task.id] = task
        self._persist()
        asyncio.create_task(self._run(task, knowledge_base_ids, requirements,
                                      as_of, max_deep_calls, output_language,
                                      research_depth))
        return task

    async def _run(self, task, knowledge_base_ids, requirements, as_of,
                   max_deep_calls, output_language, research_depth):
        task.status, task.started_at = "running", _now()
        task.phase = "starting"
        task.progress_percent = 2
        task.updated_at = task.started_at
        folder = self.root / task.id
        task.artifact_path = str(folder)
        self._persist()

        def progress(update):
            task.phase = str(update.get("phase", task.phase))
            task.progress_percent = max(
                task.progress_percent,
                min(99, int(update.get("progress_percent", task.progress_percent))))
            task.evidence_count = max(
                task.evidence_count, int(update.get("evidence_count", task.evidence_count)))
            task.updated_at = _now()
            self._persist()

        try:
            result = await self.research.run(
                task.query, knowledge_base_ids=knowledge_base_ids,
                requirements=requirements, output_dir=folder,
                as_of=as_of, max_deep_calls=max_deep_calls,
                progress=progress, output_language=output_language,
                research_depth=research_depth)
            if result.get("metrics", {}).get("status") == "failed":
                raise RuntimeError("research engine reported failure")
            task.status = "completed"
            task.phase = "completed"
            task.progress_percent = 100
            task.evidence_count = max(
                task.evidence_count, len(result.get("sources", ())))
        except Exception:
            task.status = "failed"
            task.phase = "failed"
            task.error = TaskError("research_failed", "Research task failed")
        task.completed_at = _now()
        task.updated_at = task.completed_at
        self._persist()

    def get(self, task_id):
        if task_id not in self.tasks:
            raise KeyError(task_id)
        return self.tasks[task_id]

    def list(self):
        return sorted(self.tasks.values(), key=lambda task: task.created_at, reverse=True)
