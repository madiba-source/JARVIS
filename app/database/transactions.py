from contextlib import contextmanager
from typing import Iterator
import sqlite3

from .connection import DatabaseConnectionManager
from .errors import DatabaseTransactionError


class TransactionContext:
    def __init__(self, connection_manager: DatabaseConnectionManager) -> None:
        self.conn_manager = connection_manager

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            with self.conn_manager.connection() as conn:
                conn.execute("BEGIN")
                try:
                    yield conn
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
        except DatabaseTransactionError:
            raise
        except Exception as error:
            raise DatabaseTransactionError(str(error)) from error
