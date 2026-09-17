"""Thread-safe, contiguous migration registry and history validator."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable

from .connection import DatabaseConnectionManager
from .errors import DatabaseMigrationError, DatabaseVersionError

Migration = tuple[int, str, Callable[[sqlite3.Connection], None]]


class MigrationManager:
    def __init__(self, connection_manager: DatabaseConnectionManager) -> None:
        self.conn_manager = connection_manager
        self._migrations: tuple[Migration, ...] = ()
        self._lock = threading.RLock()
        self._frozen = False

    @property
    def current_supported_version(self) -> int:
        with self._lock:
            return self._migrations[-1][0] if self._migrations else 0

    def register_migration(self, version: int, description: str, migration_func: Callable[[sqlite3.Connection], None]) -> None:
        with self._lock:
            if self._frozen:
                raise DatabaseMigrationError("migration registry is frozen")
            draft = list(self._migrations)
            if version < 1 or any(item[0] == version for item in draft):
                raise DatabaseMigrationError("invalid or duplicate migration version")
            draft.append((version, description, migration_func))
            draft.sort(key=lambda item: item[0])
            if [item[0] for item in draft] != list(range(1, len(draft) + 1)):
                raise DatabaseMigrationError("migration sequence must be contiguous from version 1")
            self._migrations = tuple(draft)

    def freeze(self) -> None:
        with self._lock:
            self._frozen = True

    def _ensure_table(self, conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, description TEXT NOT NULL, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)")

    @staticmethod
    def validate_history(versions: list[int], registered: set[int]) -> int:
        if not versions:
            return 0
        if versions != list(range(1, len(versions) + 1)):
            raise DatabaseMigrationError("migration history is not contiguous")
        if any(version not in registered for version in versions):
            unknown = next(version for version in versions if version not in registered)
            raise DatabaseVersionError(f"unknown applied migration version {unknown}")
        return versions[-1]

    def get_current_version(self) -> int:
        with self._lock:
            registered = {item[0] for item in self._migrations}
        with self.conn_manager.connection() as conn:
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()
            if not exists:
                return 0
            versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
        return self.validate_history(versions, registered)

    def apply_migrations(self, target_version: int) -> None:
        with self._lock:
            migrations = self._migrations
            registered = {item[0] for item in migrations}
        if target_version < 0 or target_version > (migrations[-1][0] if migrations else 0):
            raise DatabaseVersionError("target version is unsupported")
        with self.conn_manager.connection() as conn:
            try:
                conn.execute("BEGIN")
                self._ensure_table(conn)
                current = self.validate_history([row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")], registered)
                if current > target_version:
                    raise DatabaseVersionError("downgrade is prohibited")
                for version, description, func in migrations:
                    if current < version <= target_version:
                        func(conn)
                        conn.execute("INSERT INTO schema_migrations(version,description) VALUES(?,?)", (version, description))
                actual = self.validate_history([row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")], registered)
                if actual != target_version:
                    raise DatabaseMigrationError("migration target invariant failed")
                conn.commit()
            except Exception as error:
                conn.rollback()
                if isinstance(error, (DatabaseMigrationError, DatabaseVersionError)):
                    raise
                raise DatabaseMigrationError(str(error)) from error
