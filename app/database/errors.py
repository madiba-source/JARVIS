class DatabaseError(Exception):
    pass


class DatabaseConfigurationError(DatabaseError):
    pass


class DatabaseConnectionError(DatabaseError):
    pass


class DatabaseTransactionError(DatabaseError):
    pass


class DatabaseMigrationError(DatabaseError):
    pass


class DatabaseIntegrityError(DatabaseError):
    pass


class DatabaseCorruptedError(DatabaseError):
    pass


class DatabaseLockTimeoutError(DatabaseError):
    pass


class DatabaseBackupError(DatabaseError):
    pass


class DatabaseRestoreError(DatabaseError):
    pass


class DatabaseVersionError(DatabaseError):
    pass
