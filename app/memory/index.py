"""Explicit, single-job Qdrant synchronization. No background threads or retries."""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path
from uuid import UUID

from .embeddings import EmbeddingProvider
from .models import Scope, Status, digest
from .service import active
from .store import MemoryStore, scope_key


class QdrantIndex:
    """Local package mode only; trusted runtime chooses a dedicated data directory."""

    def __init__(self, provider: EmbeddingProvider, store: MemoryStore, path: Path | None = None,
                 emit=None) -> None:
        from qdrant_client import QdrantClient, models
        self.provider, self.store, self.config = provider, store, store.config
        if not 1 <= provider.dimension <= 1024:
            raise ValueError("unsupported embedding dimension")
        self._models = models
        self._client = QdrantClient(path=str(path)) if path else QdrantClient(":memory:")
        self._collection = "memory_" + digest(provider.model_id)[:16]
        self._slot = threading.Lock()
        self._closed = False
        self._emit = emit or (lambda *args, **kwargs: None)
        self._ensure()

    def _ensure(self) -> None:
        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                self._collection,
                vectors_config=self._models.VectorParams(
                    size=self.provider.dimension, distance=self._models.Distance.COSINE,
                ),
            )
        info = self._client.get_collection(self._collection)
        if info.config.params.vectors.size != self.provider.dimension:
            raise ValueError("index dimension mismatch; rebuild required")

    def _vector(self, text: str) -> list[float]:
        start = time.monotonic()
        vector = self.provider.embed_text(text)
        if (len(vector) != self.provider.dimension
                or any(not math.isfinite(value) for value in vector)):
            raise ValueError("invalid provider vector")
        self._emit("embedding", (time.monotonic() - start) * 1000)
        return list(vector)

    def sync(self, cancelled: threading.Event | None = None) -> int:
        if self._closed or not self._slot.acquire(blocking=False):
            return 0
        completed = 0
        try:
            self.store.expire()
            for row in self.store.pending():
                if cancelled and cancelled.is_set():
                    break
                start = time.monotonic()
                success = False
                try:
                    record = self.store.decode(row)
                    if record is None or not active(record):
                        self._client.delete(self._collection,
                                            self._models.PointIdsList(points=[row["memory_id"]]))
                    else:
                        vector = self._vector(record.content)
                        if cancelled and cancelled.is_set():
                            break
                        # Stable UUID overwrites, never appends a vector on retry.
                        self._client.upsert(self._collection, points=[
                            self._models.PointStruct(
                                id=str(record.memory_id), vector=vector,
                                payload={"scope": digest(scope_key(record.scope)),
                                         "version": record.version, "hash": record.content_hash},
                            ),
                        ], wait=True)
                        current = self.store.get(record.scope, record.memory_id)
                        if current is None or not active(current) or current.version != record.version:
                            self._client.delete(self._collection,
                                                self._models.PointIdsList(points=[row["memory_id"]]))
                            continue
                    success = True
                    completed += 1
                except Exception:
                    success = False
                finally:
                    # CAS ensures an old job cannot mark a corrected/deleted version indexed.
                    self.store.index_result(row["memory_id"], row["version"], row["status"], success)
                    self._emit("indexed" if success else "index_failed",
                               (time.monotonic() - start) * 1000, success=success)
            return completed
        finally:
            self._slot.release()

    def search(self, scope: Scope, text: str) -> dict[str, tuple[float, int]]:
        if self._closed or not self._slot.acquire(blocking=False):
            raise RuntimeError("vector index busy or closed")
        try:
            results = self._client.query_points(
                self._collection, query=self._vector(text),
                query_filter=self._models.Filter(must=[
                    self._models.FieldCondition(key="scope",
                        match=self._models.MatchValue(value=digest(scope_key(scope)))),
                ]),
                limit=self.config.max_candidates, with_payload=True, with_vectors=False,
            ).points
            return {
                str(UUID(str(point.id))): (float(point.score), int(point.payload["version"]))
                for point in results[:self.config.max_candidates]
                if math.isfinite(point.score)
            }
        finally:
            self._slot.release()

    def remove(self, memory_id: UUID) -> None:
        """Immediate best-effort point removal; sync remains the durable fallback."""
        if self._closed:
            return
        if not self._slot.acquire(blocking=False):
            raise RuntimeError("index busy")
        try:
            self._client.delete(self._collection, self._models.PointIdsList(points=[str(memory_id)]))
        finally:
            self._slot.release()

    def rebuild(self) -> None:
        """Explicit recovery after SQLite restore or model change. No automatic loop."""
        if self._closed or not self._slot.acquire(blocking=False):
            raise RuntimeError("index busy or closed")
        try:
            # Reset first: a crash after reset can safely repeat deterministic upserts.
            self.store.reset_index()
            self._client.delete_collection(self._collection)
            self._ensure()
        finally:
            self._slot.release()

    def close(self) -> None:
        with self._slot:
            if not self._closed:
                self._closed = True
                self._client.close()
                self.provider.close()