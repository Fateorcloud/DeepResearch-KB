import asyncio
import errno
import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..sufficiency import EvidenceRequirement


logger = logging.getLogger(__name__)
REQUEST_FIELDS = {
    "query", "knowledge_base_ids", "required_claims", "required_source_types",
    "minimum_distinct_sources", "require_current_version", "as_of",
    "max_deep_calls", "output_language", "research_depth", "claims_source",
    "requirement_id",
}


def _now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskError:
    code: str
    message: str


class TaskActionError(ValueError):
    def __init__(self, code, message, status_code=409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


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
    claims_source: str = "explicit"
    required_claims: tuple[str, ...] | None = None
    required_source_types: tuple[str, ...] | None = None
    minimum_distinct_sources: int | None = None
    require_current_version: bool | None = None
    as_of: str | None = None
    max_deep_calls: int | None = None
    requirement_id: str | None = None
    retry_of: str | None = None
    retry_available: bool = False


class TaskService:
    def __init__(self, research, root, *, max_concurrent_research=None):
        if max_concurrent_research is None:
            max_concurrent_research = int(os.getenv("DRK_MAX_CONCURRENT_RESEARCH", "2"))
        if type(max_concurrent_research) is not int or max_concurrent_research < 1:
            raise ValueError("max_concurrent_research must be an integer >= 1")
        self.research = research
        self.max_concurrent_research = max_concurrent_research
        self._semaphore = asyncio.Semaphore(max_concurrent_research)
        self._background_tasks: dict[str, asyncio.Task] = {}
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
                    claims_source=str(record.get("claims_source", "explicit")),
                    research_depth={"quick": "low", "standard": "medium", "deep": "high"}.get(
                        str(record.get("research_depth", "medium")),
                        str(record.get("research_depth", "medium"))),
                    required_claims=(tuple(record["required_claims"])
                                     if record.get("required_claims") is not None else None),
                    required_source_types=(tuple(record["required_source_types"])
                                           if record.get("required_source_types") is not None else None),
                    minimum_distinct_sources=record.get("minimum_distinct_sources"),
                    require_current_version=record.get("require_current_version"),
                    as_of=record.get("as_of"),
                    max_deep_calls=record.get("max_deep_calls"),
                    requirement_id=record.get("requirement_id"),
                    retry_of=record.get("retry_of"),
                    retry_available=(record.get("retry_available", True)
                                     and REQUEST_FIELDS <= record.keys()
                                     and all(record.get(key) is not None for key in (
                                         "required_claims", "required_source_types",
                                         "minimum_distinct_sources", "require_current_version",
                                         "max_deep_calls", "requirement_id"))),
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
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                os.chmod(temporary, 0o600)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.index_path)
            if hasattr(os, "O_DIRECTORY"):
                try:
                    directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                except OSError as exc:
                    if exc.errno not in {errno.EINVAL, errno.ENOTSUP, errno.ENOSYS}:
                        raise
        finally:
            temporary.unlink(missing_ok=True)

    def create(self, query, knowledge_base_ids, *, requirements=None,
               as_of=None, max_deep_calls=1, output_language="Chinese",
               research_depth="medium", claims_source="explicit", retry_of=None):
        if requirements is None:
            # Keep the existing query-only MCP contract usable while ensuring
            # ResearchEngine never receives an implicit None requirement.
            requirements = EvidenceRequirement("task-query", (query,))
        knowledge_base_ids = tuple(knowledge_base_ids)
        created_at = _now()
        task = ResearchTask(
            uuid.uuid4().hex, query, knowledge_base_ids,
            created_at=created_at, updated_at=created_at,
            output_language=output_language, research_depth=research_depth,
            claims_source=claims_source,
            required_claims=tuple(requirements.required_claims),
            required_source_types=tuple(requirements.required_source_types),
            minimum_distinct_sources=requirements.minimum_distinct_sources,
            require_current_version=requirements.require_current_version,
            as_of=as_of.isoformat() if as_of is not None else None,
            max_deep_calls=max_deep_calls, requirement_id=requirements.id,
            retry_of=retry_of, retry_available=True)
        self.tasks[task.id] = task
        self._persist()
        background = asyncio.create_task(self._run(
            task, knowledge_base_ids, requirements, as_of, max_deep_calls,
            output_language, research_depth))
        self._background_tasks[task.id] = background

        def done(future):
            self._background_tasks.pop(task.id, None)
            # Cancellation before the coroutine's first step cannot reach _run.
            if future.cancelled() and task.status in {"queued", "running"}:
                self._mark_cancelled(task)

        background.add_done_callback(done)
        return task

    async def _run(self, task, knowledge_base_ids, requirements, as_of,
                   max_deep_calls, output_language, research_depth):
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
            async with self._semaphore:
                task.status, task.started_at = "running", _now()
                task.phase = "starting"
                task.progress_percent = 2
                task.updated_at = task.started_at
                folder = self.root / task.id
                task.artifact_path = str(folder)
                self._persist()
                options = {"claims_source": task.claims_source} if task.claims_source != "explicit" else {}
                result = await self.research.run(
                    task.query, knowledge_base_ids=knowledge_base_ids,
                    requirements=requirements, output_dir=folder,
                    as_of=as_of, max_deep_calls=max_deep_calls,
                    progress=progress, output_language=output_language,
                    research_depth=research_depth, **options)
                if result.get("metrics", {}).get("status") == "failed":
                    # A failed result has no exception type; retain its existing API message.
                    task.status = task.phase = "failed"
                    task.error = TaskError("research_failed", "Research task failed")
                else:
                    task.status = task.phase = "completed"
                    task.progress_percent = 100
                    task.evidence_count = max(
                        task.evidence_count, len(result.get("sources", ())))
        except asyncio.CancelledError:
            self._mark_cancelled(task)
            raise
        except Exception as exc:
            logger.exception("Research task %s failed", task.id)
            task.status = "failed"
            task.phase = "failed"
            task.error = TaskError(
                "research_failed", f"Research task failed: {type(exc).__name__}")
        task.completed_at = _now()
        task.updated_at = task.completed_at
        self._persist()

    def _mark_cancelled(self, task):
        task.status = task.phase = "cancelled"
        task.error = TaskError("research_cancelled", "Research task was cancelled")
        task.completed_at = task.updated_at = _now()
        self._persist()

    async def cancel(self, task_id):
        task = self.get(task_id)
        background = self._background_tasks.get(task_id)
        if task.status not in {"queued", "running"} or background is None:
            raise TaskActionError("task_not_cancellable", "Research task cannot be cancelled")
        background.cancel()
        try:
            await background
        except asyncio.CancelledError:
            pass
        return task

    def retry(self, task_id, *, known_knowledge_base_ids):
        task = self.get(task_id)
        if task.status not in {"failed", "cancelled"}:
            raise TaskActionError("task_not_retryable", "Research task cannot be retried")
        if not task.retry_available:
            raise TaskActionError("retry_unavailable", "Original research parameters are unavailable")
        if any(kb_id not in known_knowledge_base_ids for kb_id in task.knowledge_base_ids):
            raise TaskActionError(
                "knowledge_base_not_found", "One or more knowledge bases do not exist", 404)
        requirements = EvidenceRequirement(
            task.requirement_id, task.required_claims, task.required_source_types,
            task.minimum_distinct_sources, task.require_current_version)
        return self.create(
            task.query, task.knowledge_base_ids, requirements=requirements,
            as_of=datetime.fromisoformat(task.as_of) if task.as_of is not None else None,
            max_deep_calls=task.max_deep_calls, output_language=task.output_language,
            research_depth=task.research_depth, claims_source=task.claims_source,
            retry_of=task.id)

    def get(self, task_id):
        if task_id not in self.tasks:
            raise KeyError(task_id)
        return self.tasks[task_id]

    def list(self):
        return sorted(self.tasks.values(), key=lambda task: task.created_at, reverse=True)
