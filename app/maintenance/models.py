"""Versioned backup manifest models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    component: str
    size: int
    sha256: str
    file_type: str = "file"


@dataclass(frozen=True)
class BackupManifest:
    backup_id: str
    format_version: int
    application_version: str
    created_at: str
    source_commit: str
    platform: str
    entries: tuple[ManifestEntry, ...]
    included_components: tuple[str, ...]
    schema_versions: dict[str, int]

    @classmethod
    def create(cls, backup_id: str, application_version: str, source_commit: str, platform: str, entries: tuple[ManifestEntry, ...], components: tuple[str, ...], schema_versions: dict[str, int] | None = None) -> "BackupManifest":
        return cls(backup_id, 1, application_version, datetime.now(timezone.utc).isoformat(), source_commit[:64], platform[:128], entries, components, dict(schema_versions or {}))

    def to_dict(self) -> dict[str, object]:
        return {"backup_id": self.backup_id, "format_version": self.format_version, "application_version": self.application_version, "created_at": self.created_at, "source_commit": self.source_commit, "platform": self.platform, "included_components": self.included_components, "schema_versions": self.schema_versions, "entries": [{"path": item.path, "component": item.component, "size": item.size, "sha256": item.sha256, "file_type": item.file_type} for item in self.entries]}
