import pytest

from app.database.config import DatabaseConfig
from app.database.connection import DatabaseConnectionManager
from app.database.errors import DatabaseTransactionError
from app.database.transactions import TransactionContext


def test_transaction_commit_and_rollback(tmp_path) -> None:
    manager = DatabaseConnectionManager(DatabaseConfig(db_path=str(tmp_path / "db.sqlite"), backup_directory=str(tmp_path / "backups")))
    tx = TransactionContext(manager)
    with tx.transaction() as conn:
        conn.execute("CREATE TABLE data(value TEXT)")
        conn.execute("INSERT INTO data VALUES ('ok')")
    with pytest.raises(DatabaseTransactionError):
        with tx.transaction() as conn:
            conn.execute("INSERT INTO data VALUES ('rollback')")
            raise RuntimeError("fail")
    with manager.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM data").fetchone()[0] == 1
