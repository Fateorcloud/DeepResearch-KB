"""Minimal standalone FastAPI application for DeepResearch-KB."""
import asyncio
import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .engine import ResearchEngine
from .knowledge import KnowledgeStore
from .services.knowledge import KnowledgeService
from .services.auth import (
    SESSION_COOKIE, AuthService, AuthenticationFailed, LoginRateLimited)
from .services.backup import BackupService
from .services.research import ResearchService
from .services.tasks import TaskService
from .directory import SUPPORTED
from .sufficiency import EvidenceRequirement


class KBCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def non_blank_name(cls, value):
        if not value.strip():
            raise ValueError("name must not be blank")
        return value.strip()


class KBRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def non_blank_name(cls, value):
        if not value.strip():
            raise ValueError("name must not be blank")
        return value.strip()


class LoginCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class TokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)

    @field_validator("label")
    @classmethod
    def non_blank_label(cls, value):
        if not value.strip():
            raise ValueError("label must not be blank")
        return value.strip()


class ResearchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    knowledge_base_ids: list[str]
    required_claims: list[str] = Field(min_length=1)
    required_source_types: list[Literal["local_import", "web_upload", "external_web"]] = Field(
        default_factory=list)
    minimum_distinct_sources: int = Field(default=1, ge=1, strict=True)
    require_current_version: bool = False
    as_of: datetime | None = None
    max_deep_calls: int = Field(default=1, ge=0, strict=True)

    @field_validator("query")
    @classmethod
    def non_blank_query(cls, value):
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()

    @field_validator("knowledge_base_ids")
    @classmethod
    def valid_kb_ids(cls, value):
        if any(not item.strip() for item in value):
            raise ValueError("knowledge_base_ids must not contain blank IDs")
        if len(set(value)) != len(value):
            raise ValueError("knowledge_base_ids must not contain duplicates")
        return value

    @field_validator("required_claims")
    @classmethod
    def non_blank_claims(cls, value):
        if any(not claim.strip() for claim in value):
            raise ValueError("required_claims must not contain blank claims")
        return [claim.strip() for claim in value]

    @field_validator("required_source_types")
    @classmethod
    def unique_source_types(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("required_source_types must not contain duplicates")
        return value

    @field_validator("as_of")
    @classmethod
    def timezone_aware_as_of(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("as_of must include a timezone")
        return value


def _error(code, message):
    return {"code": code, "message": message}


def _task_dto(task):
    data = asdict(task)
    data.pop("artifact_path", None)
    return data


def _generated_artifact_dto(artifact, id_field):
    data = asdict(artifact)
    data[id_field] = data.pop("id")
    return data


def create_app(database="data/kb.sqlite", artifact_root="data/tasks", *, store=None,
               research=None, engine=None, auth=None, backup=None,
               backup_root="data/backups"):
    store = store or KnowledgeStore(database)
    knowledge = KnowledgeService(store)
    if research is not None and engine is not None:
        raise ValueError("pass research or engine, not both")
    research = research or ResearchService(engine or ResearchEngine(store=store))
    tasks = TaskService(research, artifact_root)
    auth = auth or AuthService.from_env(store.database)
    backup = backup or BackupService(
        store.database, artifact_root=artifact_root, backup_root=backup_root)
    app = FastAPI(title="DeepResearch-KB API")

    @app.middleware("http")
    async def authentication(request, call_next):
        if request.url.path in ("/api/health", "/api/auth/login"):
            return await call_next(request)
        if not auth.configured:
            return JSONResponse(status_code=503, content={"detail": _error(
                "auth_not_configured", "Authentication is not configured")})
        authorization = request.headers.get("authorization", "")
        principal = None
        if authorization.startswith("Bearer "):
            principal = auth.authenticate_bearer(authorization[7:])
        if principal is None and not authorization:
            principal = auth.authenticate_session(request.cookies.get(SESSION_COOKIE))
        if principal is None:
            return JSONResponse(status_code=401, content={"detail": _error(
                "authentication_required", "Authentication is required")})
        if request.method not in ("GET", "HEAD", "OPTIONS") and not auth.verify_csrf(
                principal, request.headers.get("x-csrf-token")):
            return JSONResponse(status_code=403, content={"detail": _error(
                "csrf_failed", "CSRF validation failed")})
        request.state.principal = principal
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, exc):
        errors = [{"location": list(item["loc"]), "type": item["type"],
                   "message": item["msg"]} for item in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": {
            **_error("invalid_request", "Request validation failed"),
            "errors": errors}})

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/auth/login")
    def login(body: LoginCreate, request: Request):
        if not auth.configured:
            raise HTTPException(503, detail=_error(
                "auth_not_configured", "Authentication is not configured"))
        client_key = request.client.host if request.client else "unknown"
        try:
            raw_session, principal = auth.login(
                body.username, body.password, client_key=client_key)
        except LoginRateLimited:
            raise HTTPException(429, detail=_error(
                "login_rate_limited", "Login temporarily unavailable")) from None
        except AuthenticationFailed:
            raise HTTPException(401, detail=_error(
                "invalid_credentials", "Invalid username or password")) from None
        response = JSONResponse({"username": principal.username,
                                 "auth_kind": principal.kind,
                                 "csrf_token": principal.csrf_token})
        response.set_cookie(
            SESSION_COOKIE, raw_session, max_age=auth.session_ttl_seconds,
            path="/", secure=True, httponly=True, samesite="lax")
        return response

    @app.get("/api/auth/session")
    def session(request: Request):
        principal = request.state.principal
        return {"username": principal.username, "auth_kind": principal.kind,
                "csrf_token": principal.csrf_token}

    @app.post("/api/auth/logout")
    def logout(request: Request):
        principal = request.state.principal
        auth.logout(principal)
        response = JSONResponse({"status": "logged_out"})
        response.delete_cookie(SESSION_COOKIE, path="/", secure=True,
                               httponly=True, samesite="lax")
        return response

    def require_session_admin(request):
        if request.state.principal.kind != "session":
            raise HTTPException(403, detail=_error(
                "session_required", "Browser session authentication is required"))

    @app.post("/api/auth/tokens")
    def create_token(body: TokenCreate, request: Request):
        require_session_admin(request)
        issued = auth.issue_cli_token(body.label)
        return asdict(issued)

    @app.get("/api/auth/tokens")
    def list_tokens(request: Request):
        require_session_admin(request)
        return auth.list_cli_tokens()

    @app.delete("/api/auth/tokens/{token_id}")
    def revoke_token(token_id: str, request: Request):
        require_session_admin(request)
        try:
            auth.revoke_cli_token(token_id)
        except KeyError:
            raise HTTPException(404, detail=_error(
                "token_not_found", "CLI token does not exist or is already revoked"))
        return {"status": "revoked"}

    @app.get("/api/settings/status")
    def settings_status():
        return {
            "research_provider": {
                "configured": bool(os.getenv("OPENAI_API_KEY")),
                "detail": "available" if os.getenv("OPENAI_API_KEY") else "not_configured",
            },
            "web_search_provider": {
                "configured": bool(os.getenv("TAVILY_API_KEY")),
                "detail": "available" if os.getenv("TAVILY_API_KEY") else "not_configured",
            },
        }

    @app.post("/api/backups")
    async def create_backup():
        artifact = await asyncio.to_thread(backup.create_backup)
        return _generated_artifact_dto(artifact, "backup_id")

    @app.get("/api/backups/{backup_id}")
    def download_backup(backup_id: str):
        try:
            path = backup.resolve("backup", backup_id)
        except KeyError:
            raise HTTPException(404, detail=_error(
                "backup_not_found", "Backup does not exist"))
        return FileResponse(path, media_type="application/vnd.sqlite3",
                            filename=path.name)

    @app.post("/api/exports")
    async def create_export():
        artifact = await asyncio.to_thread(backup.create_export)
        return _generated_artifact_dto(artifact, "export_id")

    @app.get("/api/exports/{export_id}")
    def download_export(export_id: str):
        try:
            path = backup.resolve("export", export_id)
        except KeyError:
            raise HTTPException(404, detail=_error(
                "export_not_found", "Export does not exist"))
        return FileResponse(path, media_type="application/zip",
                            filename=path.name)

    @app.post("/api/kbs")
    def create_kb(body: KBCreate):
        try: return asdict(knowledge.create(body.name))
        except ValueError: raise HTTPException(422, detail=_error(
            "invalid_request", "Knowledge base name is invalid"))

    @app.get("/api/kbs")
    def list_kbs(): return [asdict(kb) for kb in knowledge.list()]

    @app.patch("/api/kbs/{kb_id}")
    def rename_kb(kb_id: str, body: KBRename):
        try:
            return asdict(knowledge.rename(kb_id, body.name))
        except KeyError:
            raise HTTPException(404, detail=_error(
                "knowledge_base_not_found", "Knowledge base does not exist"))

    @app.post("/api/kbs/{kb_id}/documents")
    async def upload(kb_id: str, file: UploadFile = File(...), logical_path: str = Form(...)):
        if not file.filename or Path(file.filename).name != file.filename:
            raise HTTPException(400, detail=_error(
                "invalid_filename", "Upload filename is invalid"))
        if Path(logical_path).suffix.lower() not in SUPPORTED:
            raise HTTPException(400, detail=_error(
                "unsupported_extension", "Document type is not supported"))
        if not logical_path.strip() or logical_path.replace("\\", "/").startswith("/") or ".." in Path(logical_path).parts:
            raise HTTPException(400, detail=_error(
                "invalid_logical_path", "Document logical path is invalid"))
        data = await file.read()
        if not data: raise HTTPException(400, detail=_error(
            "empty_file", "Document file is empty"))
        with tempfile.NamedTemporaryFile(prefix="drkb-upload-", suffix=Path(logical_path).suffix, delete=False) as tmp:
            tmp.write(data); staged = Path(tmp.name)
        try:
            previous = store.list_versions(kb_id, logical_path)
            version = await knowledge.ingest(kb_id, staged, logical_path=logical_path,
                                             source_type="web_upload", source_uri=f"upload://{kb_id}/{logical_path}")
            return {
                **asdict(version),
                "ingest_action": (
                    "unchanged" if previous
                    and previous[-1].content_hash == version.content_hash
                    else "imported"),
            }
        except KeyError:
            raise HTTPException(404, detail=_error(
                "knowledge_base_not_found", "Knowledge base does not exist"))
        except (ValueError, OSError):
            raise HTTPException(400, detail=_error(
                "document_ingest_failed", "Document could not be ingested"))
        finally: staged.unlink(missing_ok=True)

    @app.get("/api/kbs/{kb_id}/documents")
    def documents(kb_id):
        try: return knowledge.documents(kb_id)
        except KeyError: raise HTTPException(404, detail=_error(
            "knowledge_base_not_found", "Knowledge base does not exist"))

    @app.get("/api/kbs/{kb_id}/documents/{document_id}")
    def document(kb_id, document_id):
        try: return asdict(knowledge.document(kb_id, document_id))
        except KeyError: raise HTTPException(404, detail=_error(
            "document_not_found", "Document does not exist in this knowledge base"))

    @app.get("/api/kbs/{kb_id}/documents/{document_id}/versions")
    def versions(kb_id, document_id):
        try: return [asdict(v) for v in knowledge.versions(kb_id, document_id)]
        except KeyError: raise HTTPException(404, detail=_error(
            "document_not_found", "Document does not exist in this knowledge base"))

    @app.get("/api/kbs/{kb_id}/documents/{document_id}/versions/{version}")
    def version(kb_id, document_id, version: int):
        try: return asdict(knowledge.version(kb_id, document_id, version))
        except (KeyError, ValueError):
            raise HTTPException(404, detail=_error(
                "document_version_not_found", "Document version does not exist"))

    @app.get("/api/kbs/{kb_id}/documents/{document_id}/versions/{version}/raw")
    def raw_version(kb_id, document_id, version: int):
        try:
            item = knowledge.version(kb_id, document_id, version)
            raw = store.raw_document_version(document_id, version)
        except (KeyError, ValueError):
            raise HTTPException(404, detail=_error(
                "document_version_not_found", "Document version does not exist"))
        return Response(
            raw, media_type="application/octet-stream",
            headers={"X-Content-Hash": item.content_hash})

    @app.post("/api/research")
    async def create_research(body: ResearchCreate):
        known_ids = {kb.id for kb in knowledge.list()}
        if any(kb_id not in known_ids for kb_id in body.knowledge_base_ids):
            raise HTTPException(404, detail=_error(
                "knowledge_base_not_found", "One or more knowledge bases do not exist"))
        try:
            requirement = EvidenceRequirement(
                "http-request", tuple(body.required_claims),
                tuple(body.required_source_types), body.minimum_distinct_sources,
                body.require_current_version)
        except ValueError:
            raise HTTPException(422, detail=_error(
                "invalid_requirement", "Evidence requirement is invalid")) from None
        task = tasks.create(body.query, body.knowledge_base_ids,
                            requirements=requirement, as_of=body.as_of,
                            max_deep_calls=body.max_deep_calls)
        return {"task_id": task.id}

    @app.get("/api/research")
    def list_research():
        return [_task_dto(task) for task in tasks.list()]

    @app.get("/api/research/{task_id}")
    def status(task_id):
        try: return _task_dto(tasks.get(task_id))
        except KeyError: raise HTTPException(404, detail=_error(
            "task_not_found", "Research task does not exist"))

    def artifact(task_id, name):
        try: task = tasks.get(task_id)
        except KeyError: raise HTTPException(404, detail=_error(
            "task_not_found", "Research task does not exist"))
        if task.status != "completed": raise HTTPException(409, detail=_error(
            "task_not_completed", "Research task is not completed"))
        path = Path(task.artifact_path) / name
        if not path.exists(): raise HTTPException(404, detail=_error(
            "artifact_not_found", "Research artifact is unavailable"))
        return json.loads(path.read_text()) if path.suffix == ".json" else path.read_text()

    for route_name, artifact_name in (("sources", "sources.json"),
                                      ("trace", "trace.json"),
                                      ("metrics", "run.json"),
                                      ("run", "run.json")):
        app.get(f"/api/research/{{task_id}}/{route_name}")(
            lambda task_id, name=artifact_name: artifact(task_id, name))
    app.get("/api/research/{task_id}/report")(lambda task_id: artifact(task_id, "report.md"))
    return app


app = create_app()
