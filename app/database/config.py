"""Strict database configuration."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    db_path: str = Field(default="data/jarvis.db")
    busy_timeout_ms: int = Field(default=5000, ge=0, le=600000)
    enable_wal: bool = True
    enable_foreign_keys: bool = True
    backup_directory: str = "data/backups"
    maintenance_timeout_seconds: float = Field(default=30.0, gt=0, le=3600)

    @field_validator("db_path", "backup_directory", mode="before")
    @classmethod
    def normalize_paths(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("path must be a string")
        value = value.strip()
        if not value or "\x00" in value:
            raise ValueError("path must be non-empty and contain no null bytes")
        return value

    @model_validator(mode="after")
    def validate_path_relationships(self) -> "DatabaseConfig":
        db = Path(self.db_path).expanduser().resolve(strict=False)
        backup = Path(self.backup_directory).expanduser().resolve(strict=False)
        forbidden = {db, Path(f"{db}-wal"), Path(f"{db}-shm")}
        if backup in forbidden or db.is_relative_to(backup) or backup == db.parent:
            raise ValueError("backup directory overlaps the database or its parent")
        return self
