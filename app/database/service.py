import sqlite3
from contextlib import AbstractContextManager

from .backup import DatabaseBackupManager
from .config import DatabaseConfig
from .connection import DatabaseConnectionManager
from .health import DatabaseHealthChecker
from .integrity import IntegrityChecker
from .migrations import Migration, MigrationManager
from .restore import DatabaseRestoreManager
from .transactions import TransactionContext


class DatabaseService:
    """Trusted internal persistence infrastructure; never expose transaction() to model tools."""
    def __init__(self, config: DatabaseConfig | None = None, extension_migrations: list[Migration] | None = None) -> None:
        self.config = config or DatabaseConfig()
        self.connection_manager = DatabaseConnectionManager(self.config)
        self.transaction_context = TransactionContext(self.connection_manager)
        self.migration_manager = MigrationManager(self.connection_manager)
        self.integrity_checker = IntegrityChecker(self.connection_manager)
        self._register_base_migration()
        for version, description, func in extension_migrations or []:
            self.migration_manager.register_migration(version, description, func)
        self.migration_manager.freeze()
        self.backup_manager = DatabaseBackupManager(self.connection_manager, self.migration_manager)
        self.restore_manager = DatabaseRestoreManager(self.connection_manager, self.backup_manager)
        self.health_checker = DatabaseHealthChecker(self.config, self.connection_manager, self.integrity_checker, self.migration_manager)

    def _register_base_migration(self) -> None:
        def migration(conn: sqlite3.Connection) -> None:
            conn.execute("CREATE TABLE IF NOT EXISTS app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        self.migration_manager.register_migration(1, "base metadata", migration)

    def initialize(self) -> None:
        self.connection_manager.initialize()
        self.migration_manager.apply_migrations(self.migration_manager.current_supported_version)

    def transaction(self) -> AbstractContextManager[sqlite3.Connection]:
        return self.transaction_context.transaction()

    def backup(self, custom_path: str | None = None) -> str:
        return self.backup_manager.create_backup(custom_path)

    def restore(self, backup_path: str) -> bool:
        return self.restore_manager.restore_backup(backup_path)

    def health(self) -> dict[str, str]:
        return self.health_checker.check_health()
