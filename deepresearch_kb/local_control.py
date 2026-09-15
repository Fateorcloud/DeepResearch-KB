"""Loopback-only local control companion for cloud DeepResearch-KB."""

import asyncio
import os
import secrets
import tempfile
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .directory import ingest_dir, push_dir, scan
from .engine import ResearchEngine
from .knowledge import KnowledgeStore
from .services.research import ResearchService
from .services.tasks import TaskService
from .sufficiency import EvidenceRequirement


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


def _error(code, message):
    return {"code": code, "message": message}


class LocalControlError(Exception):
    def __init__(self, code, message, status_code=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class DirectoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directory: str = Field(default=".", min_length=1)

    @field_validator("directory")
    @classmethod
    def normalized(cls, value):
        return value.strip()


class TransferInput(DirectoryInput):
    kb_id: str = Field(min_length=1)


class ResearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    knowledge_base_ids: list[str] = Field(min_length=1)
    required_claims: list[str] = Field(default_factory=list)
    max_deep_calls: int = Field(default=1, ge=0, le=20)


class CloudInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server: str = Field(min_length=1)
    token: str = Field(min_length=1)


class AllowedRoot:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("allowed root must be a directory")

    def directory(self, relative):
        path = Path(relative)
        if path.is_absolute():
            raise LocalControlError(
                "path_outside_allowed_root", "Directory must be relative to the allowed root")
        try:
            resolved = (self.root / path).resolve(strict=True)
        except OSError:
            raise LocalControlError(
                "directory_not_found", "Directory does not exist", 404) from None
        if not resolved.is_dir():
            raise LocalControlError(
                "not_a_directory", "Selected path is not a directory")
        if not resolved.is_relative_to(self.root):
            raise LocalControlError(
                "path_outside_allowed_root", "Directory is outside the allowed root")
        return resolved

    def display(self, path):
        relative = Path(path).relative_to(self.root)
        return "." if not relative.parts else relative.as_posix()


class CloudClient:
    def __init__(self, server, token, *, client=None):
        if not server:
            self.server = None
            self.token_configured = False
            self._headers = {}
            self._owns_client = False
            self._client = None
            return
        parsed = urlsplit(server)
        if (parsed.scheme not in ("http", "https") or not parsed.netloc
                or parsed.username or parsed.password):
            raise ValueError("server must be an HTTP(S) origin")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("server must not contain a path, query, or fragment")
        self.server = f"{parsed.scheme}://{parsed.netloc}"
        self.token_configured = bool(token)
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=self.server, timeout=120)

    def close(self):
        if self._owns_client:
            self._client.close()

    def configure(self, server, token):
        replacement = CloudClient(server, token)
        old = self._client
        self.server, self.token_configured = replacement.server, replacement.token_configured
        self._headers, self._client, self._owns_client = replacement._headers, replacement._client, True
        if old is not None:
            old.close()

    def _request(self, method, path, **kwargs):
        if self._client is None:
            raise LocalControlError(
                "cloud_not_configured", "Cloud connection is not configured", 409)
        headers = {**self._headers, **kwargs.pop("headers", {})}
        try:
            response = self._client.request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (401, 403):
                raise LocalControlError(
                    "cloud_authentication_failed",
                    "Cloud token is missing, invalid, or revoked", 502) from None
            if status == 404:
                raise LocalControlError(
                    "cloud_resource_not_found", "Cloud resource does not exist", 502) from None
            raise LocalControlError(
                "cloud_request_failed", "Cloud request failed", 502) from None
        except httpx.HTTPError:
            raise LocalControlError(
                "cloud_unavailable", "Cloud server is unavailable", 502) from None

    def knowledge_bases(self):
        return self._request("GET", "/api/kbs").json()

    def push(self, root, kb_id):
        if self._client is None:
            raise LocalControlError(
                "cloud_not_configured", "Configure a cloud connection before pushing", 409)
        return push_dir(
            root, self.server, kb_id, token=None,
            client=_AuthorizedClient(self._client, self._headers))

    def download_backup(self, destination):
        if self._client is None:
            raise LocalControlError(
                "cloud_not_configured", "Configure a cloud connection before downloading backup", 409)
        artifact = self._request("POST", "/api/backups").json()
        download_url = artifact.get("download_url")
        filename = artifact.get("filename")
        if (not isinstance(download_url, str)
                or not download_url.startswith("/api/backups/")
                or not isinstance(filename, str)
                or Path(filename).name != filename or "\\" in filename):
            raise LocalControlError(
                "invalid_cloud_response", "Cloud returned an invalid backup reference", 502)
        payload = self._request("GET", download_url).content
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            prefix=".download-", suffix=".tmp", dir=destination, delete=False)
        staging = Path(handle.name)
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            final = destination / filename
            os.replace(staging, final)
        finally:
            if not handle.closed:
                handle.close()
            staging.unlink(missing_ok=True)
        return final


class _AuthorizedClient:
    """Small adapter preserving the injected client's transport in push_dir."""

    def __init__(self, client, headers):
        self.client = client
        self.headers = headers

    def post(self, path, **kwargs):
        headers = {**self.headers, **kwargs.pop("headers", {})}
        return self.client.post(path, headers=headers, **kwargs)


@dataclass
class LocalControlService:
    allowed: AllowedRoot
    cloud: CloudClient
    store: KnowledgeStore
    tasks: TaskService | None = None

    def __post_init__(self):
        if self.tasks is None:
            self.tasks = TaskService(
                ResearchService(ResearchEngine(store=self.store)),
                self.store.database.with_suffix(".tasks"))

    def scan(self, directory):
        root = self.allowed.directory(directory)
        items = [{
            "logical_path": logical,
            "size_bytes": path.stat().st_size,
            "modified_at": datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc).isoformat(),
        } for path, logical in scan(root)]
        return {"directory": self.allowed.display(root), "count": len(items), "files": items}

    async def ingest(self, directory, kb_id):
        root = self.allowed.directory(directory)
        try:
            return await ingest_dir(self.store, kb_id, root)
        except KeyError:
            raise LocalControlError(
                "local_knowledge_base_not_found",
                "Local knowledge base does not exist", 404) from None

    def push(self, directory, kb_id):
        root = self.allowed.directory(directory)
        return self.cloud.push(root, kb_id)

    def download_backup(self):
        target = self.allowed.root / ".deepresearch-kb" / "backups"
        path = self.cloud.download_backup(target)
        return {
            "filename": path.name,
            "relative_path": path.relative_to(self.allowed.root).as_posix(),
            "size_bytes": path.stat().st_size,
        }


def _asset(name):
    return files("deepresearch_kb.local_web").joinpath(name).read_text(encoding="utf-8")


def create_local_app(*, root, server, token, database="data/local-kb.sqlite",
                     service=None, allowed_hosts=None, control_token=None):
    allowed = AllowedRoot(root)
    cloud = service.cloud if service else CloudClient(server, token)
    if service is None:
        store = KnowledgeStore(database)
        service = LocalControlService(allowed, cloud, store)
    allowed_hosts = set(allowed_hosts or LOOPBACK_HOSTS)
    control_token = control_token or secrets.token_urlsafe(32)
    app = FastAPI(title="DeepResearch-KB Local Control", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def loopback_boundary(request, call_next):
        raw_host = request.headers.get("host", "")
        host = (raw_host[1:raw_host.find("]")] if raw_host.startswith("[")
                else raw_host.split(":", 1)[0])
        client = request.client.host if request.client else ""
        if host not in allowed_hosts or client not in allowed_hosts:
            return JSONResponse(status_code=403, content={"detail": _error(
                "loopback_required", "Local Control accepts loopback requests only")})
        if (request.url.path.startswith("/api/local/")
                and request.method not in ("GET", "HEAD", "OPTIONS")
                and not secrets.compare_digest(
                    request.headers.get("x-local-control-token", ""), control_token)):
            return JSONResponse(status_code=403, content={"detail": _error(
                "local_csrf_failed", "Local Control request token is invalid")})
        return await call_next(request)

    @app.exception_handler(LocalControlError)
    async def local_error(_request, exc):
        return JSONResponse(status_code=exc.status_code, content={
            "detail": _error(exc.code, exc.message)})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, exc):
        errors = [{"location": list(item["loc"]), "type": item["type"],
                   "message": item["msg"]} for item in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": {
            **_error("invalid_request", "Request validation failed"),
            "errors": errors}})

    @app.get("/", response_class=HTMLResponse)
    def index():
        return _asset("index.html").replace("__CONTROL_TOKEN__", control_token)

    @app.get("/assets/local-control.css")
    def styles():
        return Response(_asset("local-control.css"), media_type="text/css")

    @app.get("/local-control.css")
    def styles_relative():
        return Response(_asset("local-control.css"), media_type="text/css")

    @app.get("/assets/local-control.js")
    def script():
        return Response(_asset("local-control.js"), media_type="text/javascript")

    @app.get("/local-control.js")
    def script_relative():
        return Response(_asset("local-control.js"), media_type="text/javascript")

    @app.get("/api/local/status")
    def status():
        return {
            "allowed_root": str(service.allowed.root),
            "cloud_server": service.cloud.server,
            "cloud_token_configured": service.cloud.token_configured,
            "authoritative_store": "local",
            "local_database": str(service.store.database),
        }

    @app.get("/api/local/kbs")
    def local_knowledge_bases():
        return [asdict(item) for item in service.store.list_knowledge_bases()]

    @app.get("/api/local/cloud-kbs")
    async def cloud_knowledge_bases():
        return await asyncio.to_thread(service.cloud.knowledge_bases)

    @app.put("/api/local/cloud")
    def configure_cloud(body: CloudInput):
        try:
            service.cloud.configure(body.server, body.token)
        except (ValueError, LocalControlError):
            raise LocalControlError("invalid_cloud_config", "Cloud connection is invalid") from None
        return {"configured": True, "server": service.cloud.server}

    @app.post("/api/local/scan")
    async def scan_directory(body: DirectoryInput):
        return await asyncio.to_thread(service.scan, body.directory)

    @app.post("/api/local/ingest")
    async def ingest_directory(body: TransferInput):
        return await service.ingest(body.directory, body.kb_id)

    @app.post("/api/local/push")
    async def push_directory(body: TransferInput):
        return await asyncio.to_thread(service.push, body.directory, body.kb_id)

    @app.post("/api/local/backups")
    async def download_backup():
        return await asyncio.to_thread(service.download_backup)

    @app.post("/api/local/research")
    def local_research(body: ResearchInput):
        requirements = EvidenceRequirement(
            "local-web", tuple(body.required_claims or [body.query]))
        try:
            task = service.tasks.create(
                body.query, body.knowledge_base_ids,
                requirements=requirements, max_deep_calls=body.max_deep_calls)
        except (ValueError, KeyError):
            raise LocalControlError(
                "local_research_invalid", "Local research request is invalid") from None
        return {"task_id": task.id, "status": task.status}

    @app.get("/api/local/research/{task_id}")
    def local_research_status(task_id: str):
        try:
            task = service.tasks.get(task_id)
        except KeyError:
            raise LocalControlError("task_not_found", "Research task does not exist", 404)
        return {
            "id": task.id, "query": task.query, "status": task.status,
            "created_at": task.created_at, "started_at": task.started_at,
            "completed_at": task.completed_at,
            "error": asdict(task.error) if task.error else None,
        }

    @app.get("/api/local/research/{task_id}/report")
    def local_research_report(task_id: str):
        try:
            task = service.tasks.get(task_id)
        except KeyError:
            raise LocalControlError("task_not_found", "Research task does not exist", 404)
        if task.status != "completed" or not task.artifact_path:
            raise LocalControlError("task_not_completed", "Research task is not completed", 409)
        report = Path(task.artifact_path) / "report.md"
        return Response(report.read_text(encoding="utf-8"), media_type="text/markdown")

    @app.on_event("shutdown")
    def close_cloud():
        cloud.close()

    return app


def run_local_web(*, root, server, token, database, port=8765):
    import uvicorn

    app = create_local_app(
        root=root, server=server, token=token, database=database)
    print(f"Local Control: http://127.0.0.1:{port}", flush=True)
    print(f"Allowed root: {Path(root).resolve()}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
