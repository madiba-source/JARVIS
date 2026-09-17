import concurrent.futures

from app.database.config import DatabaseConfig
from app.database.service import DatabaseService


def test_concurrent_transactions(tmp_path) -> None:
    service = DatabaseService(DatabaseConfig(db_path=str(tmp_path / "db.sqlite"), backup_directory=str(tmp_path / "backups"))); service.initialize()
    with service.transaction() as conn: conn.execute("CREATE TABLE values_table(value INTEGER PRIMARY KEY)")
    def write(value):
        with service.transaction() as conn: conn.execute("INSERT INTO values_table VALUES(?)", (value,))
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool: list(pool.map(write, range(20)))
    with service.transaction() as conn: assert conn.execute("SELECT COUNT(*) FROM values_table").fetchone()[0] == 20
