import pytest

from app.database.config import DatabaseConfig
from app.database.connection import DatabaseConnectionManager
from app.database.errors import DatabaseLockTimeoutError


def test_connection_pragmas_and_gate(tmp_path) -> None:
    manager = DatabaseConnectionManager(DatabaseConfig(db_path=str(tmp_path / "db.sqlite"), backup_directory=str(tmp_path / "backups")))
    with manager.connection() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with manager.maintenance():
        with pytest.raises(DatabaseLockTimeoutError):
            with manager.connection(): pass
