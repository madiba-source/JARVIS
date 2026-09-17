"""Bounded JSON transfer. Imports preserve claims without trusting their authority."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from .models import Candidate, MemoryRecord, MemoryType, Schema, Scope, SourceKind, Status, reject_secrets
from .service import MemoryRejected, MemoryService


class Bundle(Schema):
    schema_version: Literal[1] = 1
    records: tuple[MemoryRecord, ...] = Field(max_length=512)


class ImportResult(Schema):
    imported: tuple[UUID, ...] = Field(default=(), max_length=512)
    failed: int = Field(default=0, ge=0, le=512)


class MemoryTransfer:
    def __init__(self, service: MemoryService, scope: Scope) -> None:
        self._service, self._scope = service, scope

    def export_json(self) -> str:
        with self._service.operation():
            config = self._service.config
            # Refuse silent truncation; the envelope is an explicit whole-scope snapshot.
            with self._service.store.database.transaction() as conn:
                from .store import scope_key
                total = conn.execute("SELECT count(*) FROM memories WHERE scope=? AND status='active'",
                                     (scope_key(self._scope),)).fetchone()[0]
            if total > config.max_transfer_records:
                raise MemoryRejected("scope exceeds export record limit; use database backup")
            records = self._service.store.list(self._scope, config.max_transfer_records)
            result = Bundle(records=records).model_dump_json()
            if len(result.encode()) > config.max_transfer_bytes:
                raise MemoryRejected("export byte limit")
            reject_secrets(result)
            self._service.emit("export", count=len(records))
            return result

    def import_json(self, content: str, *, approved: bool = False) -> ImportResult:
        if not approved:
            raise MemoryRejected("import requires explicit approval")
        config = self._service.config
        if len(content) > config.max_transfer_bytes or len(content.encode()) > config.max_transfer_bytes:
            raise MemoryRejected("import byte limit")
        reject_secrets(content)
        # Pydantic's bounded typed JSON parser, no Python object deserialization.
        try:
            bundle = Bundle.model_validate_json(content)
        except (ValueError, RecursionError):
            raise MemoryRejected("invalid import schema") from None
        if len(bundle.records) > config.max_transfer_records:
            raise MemoryRejected("import record limit")
        candidates = []
        seen = set()
        for record in bundle.records:
            if record.memory_id in seen:
                raise MemoryRejected("duplicate ID within import")
            seen.add(record.memory_id)
            if record.scope != self._scope or record.status is not Status.ACTIVE:
                raise MemoryRejected("import scope/status mismatch")
            if record.memory_type in (MemoryType.WORKING, MemoryType.PREFERENCE):
                raise MemoryRejected("transient memory and unverified preference imports unsupported")
            # Original source claims remain in the export/backup; active imported
            # attribution explicitly marks them unverified rather than forging a source.
            values = {key: value for key, value in record.model_dump().items() if key in Candidate.model_fields}
            values["provenance"] = {
                **record.provenance.model_dump(), "kind": SourceKind.IMPORT,
                "source_authority": min(record.provenance.source_authority, 0.3),
            }
            values["extraction_confidence"] = min(record.extraction_confidence, 0.5)
            candidate = self._service.validate(self._scope, Candidate.model_validate(values), True)
            candidates.append((record.memory_id, candidate))
        imported, failed = [], 0
        # Explicit per-record commit semantics: return partial failures, never claim atomic import.
        for identity, candidate in candidates:
            try:
                item = self._service.capture(self._scope, candidate, approved=True, memory_id=identity)
                imported.append(item.memory_id)
            except Exception:
                failed += 1
        self._service.emit("import", count=len(imported), success=failed == 0)
        return ImportResult(imported=tuple(imported), failed=failed)