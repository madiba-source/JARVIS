"""Governed memory API for trusted application adapters, not direct model access."""

from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from contextlib import contextmanager
from datetime import timedelta
from uuid import UUID

from app.core.events import EventBus
from app.observability.events import StructuredEvent
from app.observability.enums import EventType
from app.observability.metrics import MetricsRegistry

from .models import (
    Candidate, Hit, IndexStatus, MemoryRecord, MemoryType, Query, Retrieval,
    Scope, Signals, SourceKind, Status, digest, normalize, now, reject_secrets,
)
from .store import MemoryStore


class MemoryRejected(ValueError):
    pass


class MemoryBusy(MemoryRejected):
    pass


def active(record: MemoryRecord) -> bool:
    current = now()
    return (record.status is Status.ACTIVE and record.valid_from <= current
            and (record.valid_until is None or record.valid_until > current))


class MemoryService:
    """One shared instance per database/runtime; scopes bound by trusted adapters.

    `approved` is supplied only by a confirmation-backed executor or explicit
    trusted UI. It is intentionally absent from model-facing operation schemas.
    """

    def __init__(self, store: MemoryStore, event_bus: EventBus | None = None,
                 metrics: MetricsRegistry | None = None, indexer=None) -> None:
        self.store, self.config = store, store.config
        self.bus, self.metrics = event_bus or EventBus(), metrics or MetricsRegistry()
        self.indexer = indexer
        self._slots = threading.BoundedSemaphore(self.config.max_concurrent_operations)
        self._lock = threading.RLock()
        self._calls: deque[float] = deque(maxlen=self.config.max_operations_per_minute)
        self._working: dict[UUID, MemoryRecord] = {}
        self._closed = False

    @contextmanager
    def operation(self):
        if not self._slots.acquire(blocking=False):
            raise MemoryBusy("memory operation capacity reached")
        try:
            with self._lock:
                if self._closed:
                    raise MemoryBusy("memory service closed")
                current = time.monotonic()
                while self._calls and self._calls[0] <= current - 60:
                    self._calls.popleft()
                if len(self._calls) >= self.config.max_operations_per_minute:
                    raise MemoryBusy("memory rate limit reached")
                self._calls.append(current)
            yield
        finally:
            self._slots.release()

    def emit(self, action: str, duration_ms: float = 0, count: int = 1, success: bool = True) -> None:
        # Fixed action vocabulary at call sites; no content, IDs, paths or exception text.
        try:
            self.metrics.increment_counter("memory_operations_total", labels={"action": action})
            self.metrics.record_timing("memory_latency_ms", duration_ms, labels={"action": action})
            self.metrics.set_gauge("memory_count", count, labels={"action": action})
            self.bus.publish(StructuredEvent(
                event_type=EventType.MEMORY, component="memory", source="MemoryService",
                operation=f"memory.{action}", success=success, duration_ms=duration_ms,
                metadata={"count": min(count, 100000)},
            ))
        except Exception:
            # Telemetry failure cannot grant authority or roll back completed storage.
            pass

    def validate(self, scope: Scope, candidate: Candidate, approved: bool) -> Candidate:
        candidate = Candidate.model_validate(candidate.model_dump())
        scope = Scope.model_validate(scope.model_dump())
        if len(candidate.content) > self.config.max_memory_chars:
            raise MemoryRejected("memory size limit")
        metadata = candidate.model_dump(mode="json", exclude={"content"})
        if len(json.dumps(metadata).encode()) > self.config.max_metadata_bytes:
            raise MemoryRejected("metadata size limit")
        reject_secrets(candidate.content)
        reject_secrets(candidate.model_dump_json())
        if candidate.memory_type is not MemoryType.WORKING and not approved:
            raise MemoryRejected("persistent candidate requires explicit approval")
        if candidate.memory_type is MemoryType.PROJECT and scope.project_id is None:
            raise MemoryRejected("project scope required")
        if candidate.memory_type is MemoryType.CONVERSATION:
            if scope.conversation_id is None or candidate.provenance.conversation_id != scope.conversation_id:
                raise MemoryRejected("conversation provenance mismatch")
        if candidate.memory_type is MemoryType.PREFERENCE:
            if candidate.provenance.kind is not SourceKind.USER or candidate.extraction_confidence < 0.8:
                raise MemoryRejected("preference requires explicit stable user fact")
        if candidate.provenance.kind is SourceKind.DERIVED:
            if candidate.extraction_confidence < 0.5:
                raise MemoryRejected("low-confidence derived candidate discarded")
            candidate = Candidate.model_validate({
                **candidate.model_dump(), "extraction_confidence": min(0.7, candidate.extraction_confidence),
                "provenance": {**candidate.provenance.model_dump(), "source_authority": min(0.4, candidate.provenance.source_authority)},
            })
        if candidate.memory_type in (MemoryType.WORKING, MemoryType.CONVERSATION):
            ttl = (self.config.working_ttl_seconds if candidate.memory_type is MemoryType.WORKING
                   else self.config.conversation_ttl_seconds)
            ceiling = now() + timedelta(seconds=ttl)
            candidate = Candidate.model_validate({
                **candidate.model_dump(), "valid_until": min(candidate.valid_until or ceiling, ceiling),
            })
        return candidate

    def classify(self, scope: Scope, candidate: Candidate, approved: bool = False) -> str:
        try:
            return self.validate(scope, candidate, approved).memory_type.value
        except ValueError:
            return "discard"

    def capture(self, scope: Scope, candidate: Candidate, *, approved: bool = False,
                memory_id: UUID | None = None) -> MemoryRecord:
        with self.operation():
            try:
                candidate = self.validate(scope, candidate, approved)
                values = candidate.model_dump()
                if memory_id is not None:
                    values["memory_id"] = memory_id
                record = MemoryRecord(**values, scope=scope, normalized_content=normalize(candidate.content),
                                      content_hash=digest(normalize(candidate.content)))
                if record.memory_type is MemoryType.WORKING:
                    with self._lock:
                        self._working = {key: item for key, item in self._working.items() if active(item)}
                        if len(self._working) >= self.config.max_working_records:
                            raise MemoryBusy("working memory capacity reached")
                        self._working[record.memory_id] = record
                else:
                    record = self.store.put(record)
                self.emit("created")
                return record
            except Exception:
                self.emit("rejected", success=False)
                raise

    def correct(self, scope: Scope, identity: UUID, version: int, candidate: Candidate,
                *, approved: bool = False) -> MemoryRecord:
        with self.operation():
            candidate = self.validate(scope, candidate, approved)
            if candidate.memory_type is MemoryType.WORKING:
                raise MemoryRejected("working memory uses fresh capture")
            old = self.store.get(scope, identity)
            if old is None:
                raise MemoryRejected("memory inaccessible")
            record = MemoryRecord(
                **candidate.model_dump(), memory_id=identity, scope=scope,
                normalized_content=normalize(candidate.content), content_hash=digest(normalize(candidate.content)),
                version=version + 1, created_at=old.created_at, updated_at=now(),
            )
            result = self.store.put(record, expected_version=version)
            self.emit("updated")
            return result

    def transition(self, scope: Scope, identity: UUID, status: Status, *, approved: bool = False) -> bool:
        with self.operation():
            if not approved:
                raise MemoryRejected("mutation requires approval")
            with self._lock:
                working = self._working.get(identity)
                if working and working.scope == scope:
                    del self._working[identity]
                    return True
            result = self.store.transition(scope, identity, status)
            if result and self.indexer is not None:
                try:
                    self.indexer.remove(identity)
                except Exception:
                    self.emit("index_failed", success=False)
            self.emit("deleted" if status is Status.DELETED else "updated", count=int(result))
            return result

    def inspect(self, scope: Scope, identity: UUID) -> MemoryRecord | None:
        with self.operation():
            with self._lock:
                item = self._working.get(identity)
                if item and item.scope == scope and active(item):
                    return item
            result = self.store.get(scope, identity)
            self.emit("read", count=int(result is not None))
            return result

    @staticmethod
    def matches(record: MemoryRecord, scope: Scope, query: Query) -> bool:
        return (record.scope == scope and active(record)
                and (not query.types or record.memory_type in query.types)
                and (not query.tags or set(query.tags) <= set(record.tags))
                and (query.source_id is None or record.provenance.source_id == query.source_id)
                and (query.since is None or record.updated_at >= query.since)
                and (query.until is None or record.updated_at <= query.until))

    def retrieve(self, scope: Scope, query: Query) -> Retrieval:
        start = time.monotonic()
        try:
            with self.operation():
                scope = Scope.model_validate(scope.model_dump())
                query = Query.model_validate(query.model_dump())
                reject_secrets(query.text)
                dense, dense_available = {}, False
                if self.indexer is not None:
                    try:
                        dense = self.indexer.search(scope, query.text)
                        dense_available = True
                    except Exception:
                        self.emit("dense_unavailable", success=False)
                records = self.store.candidates(scope, query, tuple(dense))
                with self._lock:
                    records += tuple(item for item in self._working.values() if item.scope == scope)
                tokens = set(re.findall(r"\w+", normalize(query.text).casefold())[:32])
                hits = []
                for record in records:
                    if not self.matches(record, scope, query):
                        continue
                    words = set(re.findall(r"\w+", record.normalized_content.casefold()))
                    lexical = len(tokens & words) / max(1, len(tokens))
                    point = dense.get(str(record.memory_id))
                    # Dense matches from stale versions never influence ranking.
                    semantic = max(0., min(1., point[0])) if point and point[1] == record.version else 0.
                    if lexical == 0 and semantic < self.config.dense_threshold:
                        continue
                    age_days = max(0, (now() - record.updated_at).total_seconds() / 86400)
                    recency = 1 / (1 + age_days / 30)
                    score = (0.5 * lexical + 0.3 * semantic + 0.08 * recency + 0.05 * record.importance
                             + 0.03 * record.extraction_confidence + 0.04 * record.provenance.source_authority)
                    hits.append(Hit(record=record, signals=Signals(
                        lexical=lexical, dense=semantic, recency=recency, importance=record.importance,
                        extraction_confidence=record.extraction_confidence,
                        source_authority=record.provenance.source_authority, score=score,
                    )))
                hits.sort(key=lambda hit: (-hit.signals.score, -hit.record.updated_at.timestamp(), str(hit.record.memory_id)))
                unique, seen = [], set()
                for hit in hits:
                    key = (hit.record.content_hash, hit.record.provenance.source_id)
                    if key not in seen:
                        # Final authoritative check narrows delete/update races.
                        current = (hit.record if hit.record.memory_type is MemoryType.WORKING
                                   else self.store.get(scope, hit.record.memory_id))
                        if current is not None and active(current) and current.version == hit.record.version:
                            unique.append(hit)
                            seen.add(key)
                    if len(unique) == query.limit:
                        break
                duration = (time.monotonic() - start) * 1000
                self.emit("retrieval.completed", duration, len(records))
                return Retrieval(hits=tuple(unique), dense_available=dense_available,
                                 candidates=len(records), duration_ms=duration)
        except Exception:
            self.emit("unavailable", success=False)
            return Retrieval(available=False, duration_ms=(time.monotonic() - start) * 1000)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._working.clear()
        if self.indexer is not None:
            self.indexer.close()