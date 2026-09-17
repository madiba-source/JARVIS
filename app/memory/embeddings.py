"""Local embedding protocol and bounded Ollama MiniLM implementation."""

from __future__ import annotations

import json
import math
import threading
import time
from typing import Protocol

import httpx

from .config import MemoryConfig


class EmbeddingProvider(Protocol):
    dimension: int
    model_id: str

    def embed_text(self, text: str) -> tuple[float, ...]: ...
    def embed_batch(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]: ...
    def close(self) -> None: ...


class OllamaMiniLM:
    dimension = 384
    model_id = "all-minilm:latest"
    license = "Apache-2.0"
    # Shared across instances so adapters cannot multiply inference concurrency.
    _slot = threading.BoundedSemaphore(1)

    def __init__(self, config: MemoryConfig | None = None, endpoint: str = "http://127.0.0.1:11434") -> None:
        self.config = config or MemoryConfig()
        url = httpx.URL(endpoint)
        if (url.scheme != "http" or url.host not in {"127.0.0.1", "::1"}
                or url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment):
            raise ValueError("embedding endpoint must be a plain loopback origin")
        self._client = httpx.Client(base_url=endpoint, timeout=self.config.provider_timeout_seconds,
                                    trust_env=False, follow_redirects=False)
        self._closed = False

    def embed_text(self, text: str) -> tuple[float, ...]:
        return self.embed_batch((text,))[0]

    def embed_batch(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        if self._closed:
            raise RuntimeError("embedding provider closed")
        if not 1 <= len(texts) <= self.config.max_embedding_batch:
            raise ValueError("embedding batch limit")
        if any(not isinstance(text, str) or not text.strip() or len(text) > self.config.max_memory_chars for text in texts):
            raise ValueError("embedding input limit")
        if not self._slot.acquire(blocking=False):
            raise RuntimeError("embedding busy")
        try:
            start = time.monotonic()
            body = bytearray()
            with self._client.stream("POST", "/api/embed", json={
                "model": self.model_id, "input": list(texts), "truncate": False,
                "keep_alive": "30s", "options": {"num_thread": 2, "num_gpu": 0},
            }) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(chunk_size=8192):
                    body.extend(chunk)
                    if len(body) > 1048576 or time.monotonic() - start > self.config.provider_timeout_seconds:
                        raise TimeoutError("embedding response budget exceeded")
            raw = json.loads(body)["embeddings"]
            if not isinstance(raw, list) or len(raw) != len(texts):
                raise ValueError("embedding batch mismatch")
            result = []
            for vector in raw:
                if not isinstance(vector, list) or len(vector) != self.dimension:
                    raise ValueError("embedding dimension mismatch")
                if any(type(value) not in (int, float) or not math.isfinite(value) for value in vector):
                    raise ValueError("invalid embedding values")
                norm = math.sqrt(sum(value * value for value in vector))
                if not math.isfinite(norm) or norm <= 0:
                    raise ValueError("invalid embedding norm")
                result.append(tuple(value / norm for value in vector))
            return tuple(result)
        finally:
            self._slot.release()

    def close(self) -> None:
        self._closed = True
        self._client.close()