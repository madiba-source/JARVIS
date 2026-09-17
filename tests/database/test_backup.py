import os
import sqlite3

import pytest

from app.database.config import DatabaseConfig
from app.database.errors import DatabaseBackupError
from app.database.service import DatabaseService


def test_backup_verifies_and_rejects_alias(tmp_path) -> None:
    db = tmp_path / "db.sqlite"; service = DatabaseService(DatabaseConfig(db_path=str(db), backup_directory=str(tmp_path / "backups"))); service.initialize()
    backup = service.backup()
    assert os.path.exists(backup)
    with pytest.raises(DatabaseBackupError): service.backup(str(db))
    alias = tmp_path / "alias.sqlite"; alias.symlink_to(db)
    with pytest.raises(DatabaseBackupError): service.backup(str(alias))


def test_backup_rejects_gap_history(tmp_path) -> None:
    db = tmp_path / "db.sqlite"; service = DatabaseService(DatabaseConfig(db_path=str(db), backup_directory=str(tmp_path / "backups"))); service.initialize()
    with service.connection_manager.connection() as conn:
        conn.execute("INSERT INTO schema_migrations(version,description) VALUES(3,'bad')")
        conn.commit()
    with pytest.raises(DatabaseBackupError): service.backup()
