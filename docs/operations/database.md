# JARVIS Database Foundation

Phase 05 provides trusted internal SQLite persistence. It is not exposed to model or tool registries.

## Gate and restore semantics

Normal transactions acquire a connection lease and increment an active-operation count before opening SQLite. Restore acquires an exclusive maintenance lease, marks the gate closed to new connections, waits for active connections to drain, then stages the active database and sidecars in a unique `restore-staging/<transaction-id>` directory. A second restore is rejected. New connections attempted while the gate is closed are rejected. An active transaction is allowed to finish; arbitrary SQLite/Python work is not force-killed.

Restore rollback uses only the current transaction's staging directory. Stale staging directories cannot be reused. Cleanup is separate from rollback and failures are reported without claiming recovery from power loss, filesystem failure, or kernel crashes.

## Migrations and health

Migrations are registered atomically, protected by a lock, and frozen before runtime. Every applied history must be exactly contiguous `1..N` and use registered versions. The supported schema version is derived from the migration registry and reused by initialization, backup verification, restore verification, and health checks. Final migration targets are explicitly re-read and verified.

## Configuration and backups

Paths are normalized before validation. Blank paths and null bytes are rejected. The backup directory cannot overlap the database path or its parent. Backup destinations use resolved paths and reject active database, WAL, SHM, and existing symlink aliases. Backups use SQLite's online backup API and are integrity/history verified before return.

## Limits and security

SQLite row retention is bounded by configuration. WAL is used for normal operation and truncated on close. This is not a hard disk-size guarantee. Transactions are parameterized by callers and remain trusted internal infrastructure; model output must never receive direct SQL access.
