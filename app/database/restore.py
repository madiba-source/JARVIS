from __future__ import annotations

import shutil
import sqlite3
import uuid
from pathlib import Path

from .backup import DatabaseBackupManager
from .config import DatabaseConfig
from .connection import DatabaseConnectionManager
from .errors import DatabaseRestoreError


class DatabaseRestoreManager:
    def __init__(self, connection_manager: DatabaseConnectionManager, backup_manager: DatabaseBackupManager, config: DatabaseConfig | None = None) -> None:
        self.conn_manager = connection_manager
        self.backups = backup_manager
        self.config = config or connection_manager.config

    def restore_backup(self, backup_path: str, expected_schema_version: int | None = None) -> bool:
        try:
            backup = Path(backup_path).expanduser().resolve(strict=True)
        except FileNotFoundError as error:
            raise DatabaseRestoreError(f"backup file not found: {backup_path}") from error
        expected = self.backups.migrations.current_supported_version if expected_schema_version is None else expected_schema_version
        if self.backups.verify_backup(backup) != expected:
            raise DatabaseRestoreError("backup schema is incompatible")
        active = Path(self.config.db_path).expanduser().resolve(strict=False)
        staging = active.parent / "restore-staging" / uuid.uuid4().hex
        staging.mkdir(parents=True, exist_ok=False)
        staged_active = staging / active.name
        moved_active = staging / f"previous-{active.name}"
        moved_wal = staging / f"previous-{active.name}-wal"
        moved_shm = staging / f"previous-{active.name}-shm"
        active_staged = False
        try:
            with self.conn_manager.maintenance():
                if active.exists():
                    shutil.move(active, moved_active)
                    active_staged = True
                for sidecar, target in ((Path(f"{active}-wal"), moved_wal), (Path(f"{active}-shm"), moved_shm)):
                    if sidecar.exists(): shutil.move(sidecar, target)
                shutil.copy2(backup, staged_active)
                with sqlite3.connect(staged_active) as conn:
                    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise DatabaseRestoreError("restored database failed integrity check")
                shutil.move(staged_active, active)
            return True
        except Exception as error:
            try:
                if active_staged:
                    if active.exists(): active.unlink()
                    if moved_active.exists(): shutil.move(moved_active, active)
                    if moved_wal.exists(): shutil.move(moved_wal, Path(f"{active}-wal"))
                    if moved_shm.exists(): shutil.move(moved_shm, Path(f"{active}-shm"))
            except Exception:
                pass
            raise DatabaseRestoreError(str(error)) from error
        finally:
            shutil.rmtree(staging, ignore_errors=True)
