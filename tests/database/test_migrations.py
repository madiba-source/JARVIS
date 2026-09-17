import sqlite3
import pytest

from app.database.config import DatabaseConfig
from app.database.connection import DatabaseConnectionManager
from app.database.errors import DatabaseMigrationError, DatabaseVersionError
from app.database.migrations import MigrationManager


def make_manager(tmp_path):
    return DatabaseConnectionManager(DatabaseConfig(db_path=str(tmp_path / "db.sqlite"), backup_directory=str(tmp_path / "backups")))


def test_registration_is_atomic_and_frozen(tmp_path) -> None:
    manager = make_manager(tmp_path); migrations = MigrationManager(manager)
    migrations.register_migration(1, "one", lambda conn: None)
    with pytest.raises(DatabaseMigrationError): migrations.register_migration(3, "gap", lambda conn: None)
    assert migrations.current_supported_version == 1
    migrations.freeze()
    with pytest.raises(DatabaseMigrationError): migrations.register_migration(2, "late", lambda conn: None)


def test_unknown_and_gap_history_rejected(tmp_path) -> None:
    manager = make_manager(tmp_path); migrations = MigrationManager(manager)
    migrations.register_migration(1, "one", lambda conn: None)
    with manager.connection() as conn:
        conn.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, description TEXT)")
        conn.executemany("INSERT INTO schema_migrations VALUES(?,?)", [(1, "one"), (3, "three")]); conn.commit()
    with pytest.raises(DatabaseMigrationError): migrations.get_current_version()
    with manager.connection() as conn:
        conn.execute("DELETE FROM schema_migrations WHERE version=3"); conn.execute("INSERT INTO schema_migrations VALUES(2,'two')"); conn.commit()
    with pytest.raises(DatabaseVersionError): migrations.get_current_version()


def test_target_version_is_verified(tmp_path) -> None:
    manager = make_manager(tmp_path); migrations = MigrationManager(manager)
    migrations.register_migration(1, "one", lambda conn: None)
    with pytest.raises(DatabaseVersionError): migrations.apply_migrations(2)
    migrations.apply_migrations(1)
    assert migrations.get_current_version() == 1
