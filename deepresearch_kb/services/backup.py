"""Consistent SQLite backup and archive export service."""

import json
import os
import re
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


_ARTIFACT_ID = re.compile(r"[0-9a-f]{32}")


def _now():
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class GeneratedArtifact:
    id: str
    kind: str
    created_at: str
    filename: str
    download_url: str


class BackupService:
    def __init__(self, database, *, artifact_root, backup_root="data/backups"):
        self.database = Path(database).resolve()
        self.artifact_root = Path(artifact_root).resolve()
        self.backup_root = Path(backup_root).resolve()
        self.backup_root.mkdir(parents=True, exist_ok=True)

    def _write_snapshot(self, target):
        target = Path(target)
        with closing(sqlite3.connect(self.database)) as source, closing(
                sqlite3.connect(target)) as destination:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError("SQLite backup integrity check failed")

    def _artifact_name(self, kind, artifact_id, suffix):
        stamp = _now().strftime("%Y%m%dT%H%M%SZ")
        return f"{kind}-{stamp}-{artifact_id}{suffix}"

    def create_backup(self):
        artifact_id = uuid4().hex
        created_at = _now().isoformat()
        filename = self._artifact_name("kb", artifact_id, ".sqlite")
        final = self.backup_root / filename
        handle = tempfile.NamedTemporaryFile(
            prefix=".backup-", suffix=".tmp", dir=self.backup_root, delete=False)
        staging = Path(handle.name)
        handle.close()
        try:
            self._write_snapshot(staging)
            os.replace(staging, final)
        finally:
            staging.unlink(missing_ok=True)
        return GeneratedArtifact(
            artifact_id, "backup", created_at, filename,
            f"/api/backups/{artifact_id}")

    def _snapshot_counts(self, snapshot):
        with closing(sqlite3.connect(snapshot)) as db:
            tables = ("knowledge_base", "document", "document_version", "chunk")
            return {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in tables}

    def create_export(self):
        artifact_id = uuid4().hex
        created_at = _now().isoformat()
        filename = self._artifact_name("archive", artifact_id, ".zip")
        final = self.backup_root / filename
        snapshot_handle = tempfile.NamedTemporaryFile(
            prefix=".export-db-", suffix=".tmp", dir=self.backup_root, delete=False)
        archive_handle = tempfile.NamedTemporaryFile(
            prefix=".export-", suffix=".tmp", dir=self.backup_root, delete=False)
        snapshot = Path(snapshot_handle.name)
        staging = Path(archive_handle.name)
        snapshot_handle.close()
        archive_handle.close()
        try:
            self._write_snapshot(snapshot)
            task_files = [path for path in self.artifact_root.rglob("*")
                          if path.is_file() and not path.is_symlink()]
            manifest = {
                "format_version": 1,
                "created_at": created_at,
                "database": "kb.sqlite",
                "database_counts": self._snapshot_counts(snapshot),
                "research_artifact_files": len(task_files),
            }
            with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(snapshot, "kb.sqlite")
                archive.writestr("manifest.json", json.dumps(
                    manifest, ensure_ascii=False, indent=2))
                for path in task_files:
                    archive.write(path, (Path("tasks") / path.relative_to(
                        self.artifact_root)).as_posix())
            os.replace(staging, final)
        finally:
            snapshot.unlink(missing_ok=True)
            staging.unlink(missing_ok=True)
        return GeneratedArtifact(
            artifact_id, "export", created_at, filename,
            f"/api/exports/{artifact_id}")

    def resolve(self, kind, artifact_id):
        if kind not in ("backup", "export") or not _ARTIFACT_ID.fullmatch(artifact_id):
            raise KeyError(artifact_id)
        prefix, suffix = (("kb-", ".sqlite") if kind == "backup"
                          else ("archive-", ".zip"))
        matches = list(self.backup_root.glob(f"{prefix}*-{artifact_id}{suffix}"))
        if len(matches) != 1:
            raise KeyError(artifact_id)
        resolved = matches[0].resolve()
        if resolved.parent != self.backup_root:
            raise KeyError(artifact_id)
        return resolved
