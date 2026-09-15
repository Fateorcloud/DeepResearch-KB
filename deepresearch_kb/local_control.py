"""Loopback-only local control companion for cloud DeepResearch-KB."""

import asyncio
import os
import secrets
import tempfile
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
from .knowledge import KnowledgeStore


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

    def _request(self, method, path, **kwargs):
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
        return push_dir(
            root, self.server, kb_id, token=None,
            client=_AuthorizedClient(self._client, self._headers))

    def download_backup(self, destination):
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
    service = service or LocalControlService(
        allowed, cloud, KnowledgeStore(database))
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
            "authoritative_store": "cloud",
        }

    @app.get("/api/local/kbs")
    async def knowledge_bases():
        return await asyncio.to_thread(service.cloud.knowledge_bases)

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
