from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timezone

from .connection import DatabaseConnectionManager
from .errors import DatabaseBackupError
from .migrations import MigrationManager


class DatabaseBackupManager:
    def __init__(self, connection_manager: DatabaseConnectionManager, migration_manager: MigrationManager, backup_dir: str | None = None) -> None:
        self.conn_manager = connection_manager
        self.migrations = migration_manager
        self.backup_dir = Path(backup_dir or connection_manager.config.backup_directory)

    def _canonical_destination(self, path: Path) -> Path:
        path = path.expanduser().resolve(strict=False)
        active = Path(self.conn_manager.config.db_path).expanduser().resolve(strict=False)
        if path in {active, Path(f"{active}-wal"), Path(f"{active}-shm")}:
            raise DatabaseBackupError("backup destination collides with active database")
        if path.exists() and path.samefile(active):
            raise DatabaseBackupError("backup destination aliases active database")
        return path

    def create_backup(self, custom_backup_path: str | None = None) -> str:
        destination = self._canonical_destination(Path(custom_backup_path) if custom_backup_path else self.backup_dir / f"jarvis_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.db")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.conn_manager.connection() as source, sqlite3.connect(destination) as target:
                source.backup(target)
            self.verify_backup(destination)
            return str(destination)
        except DatabaseBackupError:
            raise
        except Exception as error:
            raise DatabaseBackupError(str(error)) from error

    def verify_backup(self, path: Path) -> int:
        try:
            with sqlite3.connect(path) as conn:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise DatabaseBackupError("backup integrity check failed")
                exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()
                if not exists:
                    raise DatabaseBackupError("backup lacks migration history")
                versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
            return self.migrations.validate_history(versions, {version for version, _, _ in self.migrations._migrations})
        except DatabaseBackupError:
            raise
        except Exception as error:
            raise DatabaseBackupError(str(error)) from error
