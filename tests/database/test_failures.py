import pytest

from app.database.config import DatabaseConfig
from app.database.errors import DatabaseRestoreError
from app.database.service import DatabaseService


def test_invalid_backup_fails_closed(tmp_path) -> None:
    invalid = tmp_path / "bad.db"; invalid.write_text("not sqlite")
    service = DatabaseService(DatabaseConfig(db_path=str(tmp_path / "db.sqlite"), backup_directory=str(tmp_path / "backups")))
    with pytest.raises(Exception): service.restore(str(invalid))
