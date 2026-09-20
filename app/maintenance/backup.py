"""Deterministic, integrity-verified, containment-safe backups."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import tempfile
import threading
import uuid
import zipfile
from enum import StrEnum
from pathlib import Path
from typing import Iterable

from app.version import __version__

from .models import BackupManifest, ManifestEntry


class BackupError(ValueError):
    pass


class RestoreMode(StrEnum):
    FULL = "full"
    SELECTIVE = "selective"
    CONFIG_ONLY = "config_only"
    USER_DATA_ONLY = "user_data_only"


_COMPONENT_DIRS = {"config": "config", "data": "data", "models": "models"}


class BackupManager:
    def __init__(self, source_root: Path, backup_root: Path, *, max_bytes: int = 512 * 1024 * 1024, max_files: int = 10_000, max_backups: int = 5) -> None:
        self.source_root = source_root.expanduser().resolve()
        self.backup_root = backup_root.expanduser().resolve()
        self.max_bytes = max_bytes
        self.max_files = max_files
        self.max_backups = max_backups
        self._lock = threading.RLock()
        if min(max_bytes, max_files, max_backups) <= 0:
            raise ValueError("backup limits must be positive")

    def create(self, *, components: Iterable[str] = ("config", "data"), source_commit: str = "") -> Path:
        selected = tuple(dict.fromkeys(components))
        if not selected or any(component not in _COMPONENT_DIRS for component in selected):
            raise BackupError("unsupported backup component")
        entries, files = self._collect(selected)
        manifest = BackupManifest.create(uuid.uuid4().hex, __version__, source_commit, platform.platform(aliased=True), tuple(entries), selected)
        self.backup_root.mkdir(parents=True, exist_ok=True)
        final = self.backup_root / f"jarvis-{manifest.backup_id}.zip"
        fd, temporary = tempfile.mkstemp(prefix=".jarvis-backup-", suffix=".tmp", dir=self.backup_root)
        os.close(fd)
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
                payload = json.dumps(manifest.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
                archive.writestr("MANIFEST.json", payload)
                for relative, source in files:
                    archive.write(source, relative)
            self.verify(Path(temporary), expected_manifest=manifest)
            os.replace(temporary, final)
            self._retain()
            return final
        except Exception as error:
            Path(temporary).unlink(missing_ok=True)
            if isinstance(error, BackupError):
                raise
            raise BackupError(str(error)) from error

    def inspect(self, archive_path: Path) -> BackupManifest:
        return self._read_manifest(archive_path)

    def verify(self, archive_path: Path, *, expected_manifest: BackupManifest | None = None) -> BackupManifest:
        manifest = expected_manifest or self._read_manifest(archive_path)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                expected = {item.path for item in manifest.entries} | {"MANIFEST.json"}
                if names != expected:
                    raise BackupError("backup contents do not match manifest")
                total = 0
                for entry in manifest.entries:
                    self._safe_member(entry.path)
                    info = archive.getinfo(entry.path)
                    if info.file_size != entry.size or info.file_size > self.max_bytes:
                        raise BackupError("backup invalid: checksum or file size mismatch")
                    data = archive.read(entry.path)
                    total += len(data)
                    if total > self.max_bytes or hashlib.sha256(data).hexdigest() != entry.sha256:
                        raise BackupError("backup invalid: checksum mismatch")
        except (zipfile.BadZipFile, KeyError, OSError) as error:
            raise BackupError("backup invalid") from error
        return manifest

    def restore(self, archive_path: Path, target_root: Path, *, mode: RestoreMode = RestoreMode.FULL, components: Iterable[str] | None = None) -> tuple[str, ...]:
        manifest = self.verify(archive_path)
        selected = set(components or manifest.included_components)
        if mode is RestoreMode.CONFIG_ONLY:
            selected = {"config"}
        elif mode is RestoreMode.USER_DATA_ONLY:
            selected = {"data"}
        elif mode is RestoreMode.SELECTIVE:
            selected &= set(manifest.included_components)
        if not selected or not selected <= set(_COMPONENT_DIRS):
            raise BackupError("invalid restore components")
        target = target_root.expanduser().resolve()
        staging = Path(tempfile.mkdtemp(prefix=".jarvis-restore-", dir=target.parent))
        restored: list[str] = []
        try:
            with zipfile.ZipFile(archive_path) as archive:
                for entry in manifest.entries:
                    if entry.component not in selected:
                        continue
                    self._safe_member(entry.path)
                    destination = (staging / entry.path).resolve()
                    if not destination.is_relative_to(staging):
                        raise BackupError("restore path escapes staging")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry.path) as source, destination.open("xb") as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                    restored.append(entry.path)
            for relative in restored:
                source = staging / relative
                destination = (target / relative).resolve()
                if not destination.is_relative_to(target):
                    raise BackupError("restore path escapes target")
                if destination.exists() or destination.is_symlink():
                    raise BackupError("restore target already exists; create a safety snapshot first")
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, destination)
            return tuple(restored)
        except Exception as error:
            if isinstance(error, BackupError):
                raise
            raise BackupError(str(error)) from error
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _collect(self, components: tuple[str, ...]) -> tuple[list[ManifestEntry], list[tuple[str, Path]]]:
        entries: list[ManifestEntry] = []
        files: list[tuple[str, Path]] = []
        total = 0
        for component in components:
            root = self.source_root / _COMPONENT_DIRS[component]
            if not root.exists():
                continue
            if root.is_symlink():
                raise BackupError("backup source cannot be a symlink")
            for path in sorted(root.rglob("*")):
                if path.is_symlink() or not path.is_file():
                    continue
                relative = path.relative_to(self.source_root).as_posix()
                size = path.stat().st_size
                total += size
                if len(files) >= self.max_files or total > self.max_bytes:
                    raise BackupError("backup resource limit exceeded")
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                entries.append(ManifestEntry(relative, component, size, digest))
                files.append((relative, path))
        return entries, files

    def _read_manifest(self, archive_path: Path) -> BackupManifest:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                raw = json.loads(archive.read("MANIFEST.json"))
            if raw.get("format_version") != 1 or not isinstance(raw.get("entries"), list):
                raise BackupError("malformed backup manifest")
            entries = tuple(ManifestEntry(str(item["path"]), str(item["component"]), int(item["size"]), str(item["sha256"]), str(item.get("file_type", "file"))) for item in raw["entries"])
            if len(entries) > self.max_files or len({item.path for item in entries}) != len(entries):
                raise BackupError("invalid backup manifest entries")
            return BackupManifest(str(raw["backup_id"]), 1, str(raw["application_version"]), str(raw["created_at"]), str(raw.get("source_commit", "")), str(raw.get("platform", "")), entries, tuple(str(item) for item in raw["included_components"]), {str(key): int(value) for key, value in raw.get("schema_versions", {}).items()})
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, zipfile.BadZipFile, OSError) as error:
            raise BackupError("malformed backup manifest") from error

    @staticmethod
    def _safe_member(name: str) -> None:
        path = Path(name)
        if not name or path.is_absolute() or ".." in path.parts or "\\" in name or name.startswith("/"):
            raise BackupError("unsafe backup path")

    def _retain(self) -> None:
        backups = sorted(self.backup_root.glob("jarvis-*.zip"), key=lambda item: item.stat().st_mtime, reverse=True)
        for old in backups[self.max_backups:]:
            old.unlink(missing_ok=True)
