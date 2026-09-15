"""Loopback-only local-first control companion for DeepResearch-KB."""

import asyncio
import json
import os
import secrets
import tempfile
from contextlib import asynccontextmanager
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
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


class KnowledgeBaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def non_blank_name(cls, value):
        if not value.strip():
            raise ValueError("name must not be blank")
        return value.strip()


class TransferInput(DirectoryInput):
    kb_id: str = Field(min_length=1)


class ResearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    knowledge_base_ids: list[str] = Field(min_length=1)
    required_claims: list[str] = Field(default_factory=list)
    required_source_types: list[Literal[
        "local_import", "web_upload", "external_web"]] = Field(default_factory=list)
    minimum_distinct_sources: int = Field(default=1, ge=1, strict=True)
    require_current_version: bool = False
    as_of: datetime | None = None
    max_deep_calls: int = Field(default=1, ge=0, le=20, strict=True)
    output_language: Literal["Chinese", "English"] = "Chinese"
    research_depth: Literal["low", "medium", "high"] = "medium"

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


class ProviderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    openai_api_key: str | None = Field(default=None, max_length=4096)
    deepseek_api_key: str | None = Field(default=None, max_length=4096)
    tavily_api_key: str | None = Field(default=None, max_length=4096)
    openai_base_url: str | None = Field(default=None, max_length=2048)
    deepseek_base_url: str | None = Field(default=None, max_length=2048)
    fast_llm: str | None = Field(default=None, max_length=256)
    smart_llm: str | None = Field(default=None, max_length=256)
    strategic_llm: str | None = Field(default=None, max_length=256)

    @field_validator("openai_api_key", "deepseek_api_key", "tavily_api_key",
                     "openai_base_url", "deepseek_base_url", "fast_llm",
                     "smart_llm", "strategic_llm")
    @classmethod
    def normalize_value(cls, value):
        return value.strip() if value else None

    @field_validator("fast_llm", "smart_llm", "strategic_llm")
    @classmethod
    def supported_llm(cls, value):
        if value is not None and not value.startswith(("openai:", "deepseek:")):
            raise ValueError("local provider must be openai or deepseek")
        return value


class CloudInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server: str = Field(min_length=1)
    token: str = Field(min_length=1)


class PullInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cloud_kb_id: str = Field(min_length=1)
    local_kb_id: str = Field(min_length=1)


class SyncLedger:
    """Records last common content hashes for explicit local/cloud transfers."""

    def __init__(self, path):
        self.path = Path(path).resolve()

    def _load(self):
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _key(server, local_kb_id, cloud_kb_id, logical_path):
        return "\n".join((server, local_kb_id, cloud_kb_id, logical_path))

    def get(self, server, local_kb_id, cloud_kb_id, logical_path):
        return self._load().get(self._key(
            server, local_kb_id, cloud_kb_id, logical_path))

    def set(self, server, local_kb_id, cloud_kb_id, logical_path, digest):
        data = self._load()
        data[self._key(server, local_kb_id, cloud_kb_id, logical_path)] = digest
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".sync-", suffix=".tmp",
            dir=self.path.parent, delete=False)
        staging = Path(handle.name)
        try:
            json.dump(data, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            os.chmod(staging, 0o600)
            os.replace(staging, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if not handle.closed:
                handle.close()
            staging.unlink(missing_ok=True)

    def count(self, server, local_kb_id, cloud_kb_id):
        prefix = "\n".join((server, local_kb_id, cloud_kb_id, ""))
        return sum(key.startswith(prefix) for key in self._load())


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
        try:
            replacement.knowledge_bases()
        except Exception:
            replacement.close()
            raise
        old, old_owned = self._client, self._owns_client
        self.server, self.token_configured = replacement.server, replacement.token_configured
        self._headers = replacement._headers
        self._client, self._owns_client = replacement._client, replacement._owns_client
        if old_owned and old is not None:
            old.close()

    def clear(self):
        old, old_owned = self._client, self._owns_client
        self.server = None
        self.token_configured = False
        self._headers = {}
        self._client = None
        self._owns_client = False
        if old_owned and old is not None:
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

    def documents(self, kb_id):
        return self._request("GET", f"/api/kbs/{kb_id}/documents").json()

    def versions(self, kb_id, document_id):
        return self._request(
            "GET", f"/api/kbs/{kb_id}/documents/{document_id}/versions").json()

    def raw_version(self, kb_id, document_id, version):
        return self._request(
            "GET", f"/api/kbs/{kb_id}/documents/{document_id}/versions/{version}/raw")

    def upload(self, kb_id, logical_path, raw):
        filename = Path(logical_path).name
        return self._request(
            "POST", f"/api/kbs/{kb_id}/documents",
            data={"logical_path": logical_path},
            files={"file": (filename, raw, "application/octet-stream")}).json()

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


class LocalConfigStore:
    """Permission-restricted local cloud connection settings."""

    def __init__(self, path):
        self.path = Path(path).resolve()

    def load(self):
        if not self.path.exists():
            return None, None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            server, token = data.get("server"), data.get("token")
            return (server, token) if isinstance(server, str) and isinstance(token, str) else (None, None)
        except (OSError, ValueError):
            return None, None

    def save(self, server, token):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".cloud-", suffix=".tmp",
            dir=self.path.parent, delete=False)
        staging = Path(handle.name)
        try:
            json.dump({"server": server, "token": token}, handle)
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            os.chmod(staging, 0o600)
            os.replace(staging, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if not handle.closed:
                handle.close()
            staging.unlink(missing_ok=True)

    def clear(self):
        self.path.unlink(missing_ok=True)


class LocalProviderConfigStore:
    """Permission-restricted local-only provider credentials.

    This file is deliberately separate from the SQLite database and cloud
    connection token. It is never included in push, pull, or backup data.
    """

    KEYS = (
        "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "TAVILY_API_KEY",
        "OPENAI_BASE_URL", "DEEPSEEK_BASE_URL",
        "FAST_LLM", "SMART_LLM", "STRATEGIC_LLM")

    def __init__(self, path):
        self.path = Path(path).resolve()

    def load(self):
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {key: value for key, value in data.items()
                if key in self.KEYS and isinstance(value, str) and value}

    def save(self, values):
        clean = {key: value for key, value in values.items()
                 if key in self.KEYS and isinstance(value, str) and value}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".providers-", suffix=".tmp",
            dir=self.path.parent, delete=False)
        staging = Path(handle.name)
        try:
            json.dump(clean, handle)
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            os.chmod(staging, 0o600)
            os.replace(staging, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if not handle.closed:
                handle.close()
            staging.unlink(missing_ok=True)

    def clear(self):
        self.path.unlink(missing_ok=True)


@dataclass
class LocalControlService:
    allowed: AllowedRoot
    cloud: CloudClient
    store: KnowledgeStore
    tasks: TaskService | None = None
    config: LocalConfigStore | None = None
    provider_config: LocalProviderConfigStore | None = None
    sync: SyncLedger | None = None

    def __post_init__(self):
        self._provider_env_baseline = {
            key: os.environ.get(key) for key in LocalProviderConfigStore.KEYS}
        self.apply_provider_config()
        if self.tasks is None:
            self.tasks = TaskService(
                ResearchService(ResearchEngine(store=self.store)),
                self.store.database.with_suffix(".tasks"))
        if self.sync is None:
            self.sync = SyncLedger(self.store.database.with_suffix(".sync.json"))

    def apply_provider_config(self):
        values = self.provider_config.load() if self.provider_config else {}
        for key in LocalProviderConfigStore.KEYS:
            if key in values:
                os.environ[key] = values[key]
            else:
                original = getattr(self, "_provider_env_baseline", {}).get(key)
                if original is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = original

    def set_provider_config(self, updates):
        if self.provider_config is None:
            raise LocalControlError(
                "provider_config_unavailable",
                "Local provider configuration is unavailable", 503)
        values = self.provider_config.load()
        for key, value in updates.items():
            if value:
                values[key] = value
            else:
                values.pop(key, None)
        self.provider_config.save(values)
        self.apply_provider_config()

    def provider_status(self):
        values = self.provider_config.load() if self.provider_config else {}
        configured = {
            "openai": bool(values.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")),
            "deepseek": bool(values.get("DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_KEY")),
        }
        return {
            "research": {"configured": any(configured.values())},
            "web_search": {"configured": bool(values.get("TAVILY_API_KEY")
                                               or os.getenv("TAVILY_API_KEY"))},
            "llm_providers": configured,
            "roles": {
                "fast": values.get("FAST_LLM") or os.getenv("FAST_LLM")
                        or "openai:gpt-5.4-mini",
                "smart": values.get("SMART_LLM") or os.getenv("SMART_LLM")
                         or "openai:gpt-5.4",
                "strategic": values.get("STRATEGIC_LLM") or os.getenv("STRATEGIC_LLM")
                             or "openai:gpt-5.4",
            },
        }

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

    def documents(self, kb_id):
        try:
            result = []
            for document in self.store.list_documents(kb_id):
                versions = self.store.list_versions_by_document(kb_id, document["id"])
                latest = versions[-1]
                result.append({
                    **document,
                    "version": latest.version,
                    "source_type": latest.source_type,
                    "updated_at": latest.updated_at,
                    "status": latest.status,
                })
            return result
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

    def _cloud_documents(self, cloud_kb_id):
        result = {}
        for document in self.cloud.documents(cloud_kb_id):
            versions = self.cloud.versions(cloud_kb_id, document["id"])
            if versions:
                result[document["logical_path"]] = (document, versions[-1])
        return result

    def transfer_overview(self, local_kb_id, cloud_kb_id):
        known = {item.id for item in self.store.list_knowledge_bases()}
        if local_kb_id not in known:
            raise LocalControlError(
                "local_knowledge_base_not_found", "Local knowledge base does not exist", 404)
        local_versions = []
        for document in self.store.list_documents(local_kb_id):
            versions = self.store.list_versions_by_document(local_kb_id, document["id"])
            if versions:
                local_versions.append(versions[-1])
        cloud_versions = [latest for _, latest in self._cloud_documents(cloud_kb_id).values()]

        def summary(versions):
            return {
                "document_count": len(versions),
                "updated_at": max(
                    (item["updated_at"] if isinstance(item, dict) else item.updated_at
                     for item in versions), default=None),
            }

        return {
            "local": summary(local_versions),
            "cloud": summary(cloud_versions),
            "baseline": {
                "tracked_documents": self.sync.count(
                    self.cloud.server, local_kb_id, cloud_kb_id),
                "strategy": "per_document_content_hash",
            },
        }

    def push_knowledge_base(self, local_kb_id, cloud_kb_id):
        known = {item.id for item in self.store.list_knowledge_bases()}
        if local_kb_id not in known:
            raise LocalControlError(
                "local_knowledge_base_not_found", "Local knowledge base does not exist", 404)
        cloud = self._cloud_documents(cloud_kb_id)
        result = {
            "imported": 0, "unchanged": 0, "conflicts": 0,
            "failed": 0, "errors": [], "conflict_items": []}
        for document in self.store.list_documents(local_kb_id):
            logical_path = document["logical_path"]
            try:
                local = self.store.list_versions_by_document(
                    local_kb_id, document["id"])[-1]
                remote = cloud.get(logical_path)
                cloud_hash = remote[1]["content_hash"] if remote else None
                baseline = self.sync.get(
                    self.cloud.server, local_kb_id, cloud_kb_id, logical_path)
                if cloud_hash == local.content_hash:
                    result["unchanged"] += 1
                    self.sync.set(
                        self.cloud.server, local_kb_id, cloud_kb_id,
                        logical_path, local.content_hash)
                    continue
                if cloud_hash is not None and baseline != cloud_hash:
                    reason = ("cloud_changed_pull_recommended"
                              if baseline == local.content_hash
                              else "local_and_cloud_versions_differ")
                    result["conflicts"] += 1
                    result["conflict_items"].append({
                        "logical_path": logical_path,
                        "local_hash": local.content_hash,
                        "cloud_hash": cloud_hash,
                        "reason": reason,
                    })
                    continue
                raw = self.store.raw_document_version(
                    document["id"], local.version)
                uploaded = self.cloud.upload(cloud_kb_id, logical_path, raw)
                self.sync.set(
                    self.cloud.server, local_kb_id, cloud_kb_id,
                    logical_path, uploaded["content_hash"])
                result["imported"] += 1
            except Exception as exc:
                result["failed"] += 1
                result["errors"].append({
                    "logical_path": logical_path,
                    "error_type": type(exc).__name__})
        return result

    async def pull(self, cloud_kb_id, local_kb_id):
        known = {item.id for item in self.store.list_knowledge_bases()}
        if local_kb_id not in known:
            raise LocalControlError(
                "local_knowledge_base_not_found", "Local knowledge base does not exist", 404)
        result = {
            "imported": 0, "unchanged": 0, "conflicts": 0,
            "failed": 0, "errors": [], "conflict_items": []}
        for document in self.cloud.documents(cloud_kb_id):
            try:
                versions = self.cloud.versions(cloud_kb_id, document["id"])
                latest = versions[-1]
                logical_path = document["logical_path"]
                local_versions = self.store.list_versions(local_kb_id, logical_path)
                baseline = self.sync.get(
                    self.cloud.server, local_kb_id, cloud_kb_id, logical_path)
                if local_versions and local_versions[-1].content_hash == latest["content_hash"]:
                    result["unchanged"] += 1
                    self.sync.set(
                        self.cloud.server, local_kb_id, cloud_kb_id,
                        logical_path, latest["content_hash"])
                    continue
                if (local_versions
                        and baseline != local_versions[-1].content_hash):
                    reason = ("local_changed_push_recommended"
                              if baseline == latest["content_hash"]
                              else "local_and_cloud_versions_differ")
                    result["conflicts"] += 1
                    result["conflict_items"].append({
                        "logical_path": logical_path,
                        "local_hash": local_versions[-1].content_hash,
                        "cloud_hash": latest["content_hash"],
                        "reason": reason,
                    })
                    continue
                response = self.cloud.raw_version(
                    cloud_kb_id, document["id"], latest["version"])
                suffix = Path(logical_path).suffix
                handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
                staged = Path(handle.name)
                try:
                    handle.write(response.content)
                    handle.close()
                    await self.store.ingest(
                        local_kb_id, staged, logical_path=logical_path,
                        source_type=latest["source_type"],
                        source_uri=f"cloud://{cloud_kb_id}/{document['id']}/v{latest['version']}",
                        updated_at=datetime.fromisoformat(latest["updated_at"]))
                finally:
                    if not handle.closed:
                        handle.close()
                    staged.unlink(missing_ok=True)
                result["imported"] += 1
                self.sync.set(
                    self.cloud.server, local_kb_id, cloud_kb_id,
                    logical_path, latest["content_hash"])
            except Exception as exc:
                result["failed"] += 1
                result["errors"].append({
                    "logical_path": document.get("logical_path", "unknown"),
                    "error_type": type(exc).__name__})
        return result


def _asset(name):
    return files("deepresearch_kb.local_web").joinpath(name).read_text(encoding="utf-8")


def _render_report_pdf(report_path):
    """Render a completed Markdown report to a private, cached PDF artifact."""
    pdf_path = report_path.with_suffix(".pdf")
    if (pdf_path.is_file()
            and pdf_path.stat().st_mtime_ns >= report_path.stat().st_mtime_ns):
        return pdf_path

    nonce = secrets.token_hex(8)
    staged_path = report_path.parent / f".report-{nonce}.pdf"
    staged_css = report_path.parent / f".report-{nonce}.css"
    try:
        from markdown import markdown
        from weasyprint import CSS, HTML
        from weasyprint.text.fonts import FontConfiguration

        font_candidates = [
            Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
            Path("/mnt/c/Windows/Fonts/simhei.ttf"),
            Path("/mnt/c/Windows/Fonts/msyh.ttc"),
            Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/simhei.ttf",
        ]
        cjk_font = next((path for path in font_candidates if path.is_file()), None)
        font_face = (f'@font-face {{ font-family: "Report CJK"; '
                     f'src: url("{cjk_font.resolve().as_uri()}"); }}\n'
                     if cjk_font else "")
        staged_css.write_text(
            font_face + _asset("report-print.css"), encoding="utf-8")
        staged_css.chmod(0o600)
        html = markdown(
            report_path.read_text(encoding="utf-8"),
            extensions=["extra", "sane_lists"],
        )
        font_config = FontConfiguration()
        stylesheet = CSS(filename=staged_css, font_config=font_config)
        HTML(string=html, base_url=report_path.parent).write_pdf(
            staged_path, stylesheets=[stylesheet], font_config=font_config)
        if not staged_path.is_file() or not staged_path.read_bytes().startswith(b"%PDF"):
            raise RuntimeError("PDF renderer did not produce a PDF")
        staged_path.chmod(0o600)
        os.replace(staged_path, pdf_path)
    except Exception:
        staged_path.unlink(missing_ok=True)
        raise LocalControlError(
            "report_pdf_unavailable", "PDF report could not be generated", 503
        ) from None
    finally:
        staged_css.unlink(missing_ok=True)
    return pdf_path


def create_local_app(*, root, server, token, database="data/local-kb.sqlite",
                     service=None, allowed_hosts=None, control_token=None):
    allowed = AllowedRoot(root)
    database_path = Path(database)
    config = LocalConfigStore(database_path.with_suffix(".cloud.json"))
    provider_database = Path(service.store.database) if service is not None else database_path
    provider_config = LocalProviderConfigStore(
        provider_database.with_suffix(".providers.json"))
    if service is None and not server:
        saved_server, saved_token = config.load()
        server, token = saved_server, saved_token
    cloud = service.cloud if service else CloudClient(server, token)
    if service is None:
        store = KnowledgeStore(database)
        service = LocalControlService(
            allowed, cloud, store, config=config, provider_config=provider_config)
    elif service.provider_config is None:
        service.provider_config = provider_config
        service.apply_provider_config()
    allowed_hosts = set(allowed_hosts or LOOPBACK_HOSTS)
    control_token = control_token or secrets.token_urlsafe(32)
    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            cloud.close()

    app = FastAPI(
        title="DeepResearch-KB Local Control", docs_url=None, redoc_url=None,
        lifespan=lifespan)

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
            "providers": service.provider_status(),
        }

    @app.put("/api/local/providers")
    def configure_providers(body: ProviderInput):
        fields = {
            "openai_api_key": "OPENAI_API_KEY",
            "deepseek_api_key": "DEEPSEEK_API_KEY",
            "tavily_api_key": "TAVILY_API_KEY",
            "openai_base_url": "OPENAI_BASE_URL",
            "deepseek_base_url": "DEEPSEEK_BASE_URL",
            "fast_llm": "FAST_LLM",
            "smart_llm": "SMART_LLM",
            "strategic_llm": "STRATEGIC_LLM",
        }
        updates = {environment: getattr(body, field) for field, environment in fields.items()
                   if field in body.model_fields_set}
        service.set_provider_config(updates)
        return {"providers": service.provider_status()}

    @app.delete("/api/local/providers")
    def clear_providers():
        if service.provider_config is not None:
            service.provider_config.clear()
            service.apply_provider_config()
        return {"providers": service.provider_status()}

    @app.get("/api/local/kbs")
    def local_knowledge_bases():
        return [asdict(item) for item in service.store.list_knowledge_bases()]

    @app.get("/api/local/kbs/{kb_id}/documents")
    def local_documents(kb_id: str):
        return service.documents(kb_id)

    @app.post("/api/local/kbs")
    def create_local_knowledge_base(body: KnowledgeBaseInput):
        return asdict(service.store.create_knowledge_base(body.name))

    @app.get("/api/local/cloud-kbs")
    async def cloud_knowledge_bases():
        return await asyncio.to_thread(service.cloud.knowledge_bases)

    @app.put("/api/local/cloud")
    def configure_cloud(body: CloudInput):
        try:
            service.cloud.configure(body.server, body.token)
        except (ValueError, LocalControlError):
            raise LocalControlError("invalid_cloud_config", "Cloud connection is invalid") from None
        if service.config:
            service.config.save(service.cloud.server, body.token)
        return {"configured": True, "server": service.cloud.server}

    @app.delete("/api/local/cloud")
    def disconnect_cloud():
        service.cloud.clear()
        if service.config:
            service.config.clear()
        return {"configured": False}

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

    @app.post("/api/local/pull")
    async def pull_cloud(body: PullInput):
        return await service.pull(body.cloud_kb_id, body.local_kb_id)

    @app.post("/api/local/sync/push")
    async def push_local_knowledge_base(body: PullInput):
        return await asyncio.to_thread(
            service.push_knowledge_base, body.local_kb_id, body.cloud_kb_id)

    @app.get("/api/local/transfers/overview")
    async def transfer_overview(local_kb_id: str, cloud_kb_id: str):
        return await asyncio.to_thread(
            service.transfer_overview, local_kb_id, cloud_kb_id)

    @app.get("/api/local/research")
    def local_research_history():
        return [{
            "id": task.id,
            "query": task.query,
            "knowledge_base_ids": list(task.knowledge_base_ids),
            "status": task.status,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "updated_at": task.updated_at,
            "phase": task.phase,
            "progress_percent": task.progress_percent,
            "evidence_count": task.evidence_count,
            "error": asdict(task.error) if task.error else None,
        } for task in service.tasks.list()]

    @app.post("/api/local/research")
    async def local_research(body: ResearchInput):
        known_ids = {kb.id for kb in service.store.list_knowledge_bases()}
        if any(kb_id not in known_ids for kb_id in body.knowledge_base_ids):
            raise LocalControlError(
                "local_knowledge_base_not_found",
                "One or more local knowledge bases do not exist", 404)
        try:
            requirements = EvidenceRequirement(
                "local-web", tuple(body.required_claims or [body.query]),
                tuple(body.required_source_types), body.minimum_distinct_sources,
                body.require_current_version)
            task = service.tasks.create(
                body.query, body.knowledge_base_ids,
                requirements=requirements, as_of=body.as_of,
                max_deep_calls=body.max_deep_calls,
                output_language=body.output_language,
                research_depth=body.research_depth)
        except ValueError:
            raise LocalControlError(
                "invalid_requirement", "Evidence requirement is invalid", 422) from None
        return {"task_id": task.id, "status": task.status}

    @app.get("/api/local/research/{task_id}")
    def local_research_status(task_id: str):
        try:
            task = service.tasks.get(task_id)
        except KeyError:
            raise LocalControlError("task_not_found", "Research task does not exist", 404)
        return {
            "id": task.id, "query": task.query, "status": task.status,
            "knowledge_base_ids": list(task.knowledge_base_ids),
            "created_at": task.created_at, "started_at": task.started_at,
            "completed_at": task.completed_at,
            "updated_at": task.updated_at, "phase": task.phase,
            "progress_percent": task.progress_percent,
            "evidence_count": task.evidence_count,
            "error": asdict(task.error) if task.error else None,
        }

    def local_research_artifact(task_id, name):
        try:
            task = service.tasks.get(task_id)
        except KeyError:
            raise LocalControlError("task_not_found", "Research task does not exist", 404)
        if task.status != "completed" or not task.artifact_path:
            raise LocalControlError("task_not_completed", "Research task is not completed", 409)
        path = Path(task.artifact_path) / name
        if not path.is_file():
            raise LocalControlError(
                "artifact_not_found", "Research artifact is unavailable", 404)
        if path.suffix == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        return Response(path.read_text(encoding="utf-8"), media_type="text/markdown")

    for route_name, artifact_name in (
            ("sources", "sources.json"), ("trace", "trace.json"),
            ("metrics", "run.json")):
        app.get(f"/api/local/research/{{task_id}}/{route_name}")(
            lambda task_id, name=artifact_name: local_research_artifact(task_id, name))
    app.get("/api/local/research/{task_id}/report")(
        lambda task_id: local_research_artifact(task_id, "report.md"))

    @app.get("/api/local/research/{task_id}/download")
    def download_research_report(
            task_id: str, format: Literal["md", "pdf"] = "md"):
        try:
            task = service.tasks.get(task_id)
        except KeyError:
            raise LocalControlError(
                "task_not_found", "Research task does not exist", 404) from None
        if task.status != "completed" or not task.artifact_path:
            raise LocalControlError(
                "task_not_completed", "Research task is not completed", 409)
        report_path = Path(task.artifact_path) / "report.md"
        if not report_path.is_file():
            raise LocalControlError(
                "artifact_not_found", "Research artifact is unavailable", 404)
        download_path = (
            report_path if format == "md" else _render_report_pdf(report_path))
        return FileResponse(
            download_path,
            media_type=("text/markdown; charset=utf-8"
                        if format == "md" else "application/pdf"),
            filename=f"research-{task.id}.{format}",
        )

    return app


def run_local_web(*, root, server, token, database, port=8765):
    import uvicorn

    app = create_local_app(
        root=root, server=server, token=token, database=database)
    print(f"Local Control: http://127.0.0.1:{port}", flush=True)
    print(f"Allowed root: {Path(root).resolve()}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
