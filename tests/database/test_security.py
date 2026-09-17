from app.database.config import DatabaseConfig
from app.database.service import DatabaseService


def test_parameterized_queries_remain_internal(tmp_path) -> None:
    service = DatabaseService(DatabaseConfig(db_path=str(tmp_path / "db.sqlite"), backup_directory=str(tmp_path / "backups"))); service.initialize()
    with service.transaction() as conn:
        conn.execute("CREATE TABLE users(name TEXT)"); conn.execute("INSERT INTO users VALUES(?)", ("alice",))
        assert conn.execute("SELECT * FROM users WHERE name=?", ("alice' OR '1'='1",)).fetchall() == []
