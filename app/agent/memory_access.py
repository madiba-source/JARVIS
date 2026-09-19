"""Phase 05 memory integration for the agent runtime.

The runtime never opens SQLite, never touches Qdrant and never imports the
memory store. It calls the same registered, scope-bound memory capabilities that
Phase 05 exposes, through the same policy gateway as every other step. Retrieved
text is data: it can inform a plan, and it can never authorize one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.policy.models import ToolRequest

from .errors import AgentError
from .gateway import ExecutionGateway

RETRIEVE = "retrieve_memory"
INSPECT = "inspect_memory"
STORE = "store_memory_candidate"
UPDATE = "update_memory"
DELETE = "delete_memory"

MAX_QUERY_CHARS = 512
MAX_CONTENT_CHARS = 8192
MAX_RETURNED_HITS = 8
SUMMARY_LIMIT = 1024


@dataclass(frozen=True)
class MemoryQueryResult:
    available: bool
    hits: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class MemoryWriteResult:
    accepted: bool
    pending_confirmation: bool = False
    memory_id: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class MemoryCapabilities:
    readable: bool = False
    writable: bool = False
    details: dict[str, Any] = field(default_factory=dict)


class MemoryAccessor:
    """Scope-bound memory reads and writes mediated by the policy gateway."""

    def __init__(self, gateway: ExecutionGateway) -> None:
        self._gateway = gateway
        catalog = gateway.catalog
        self._readable = catalog.has_operation(RETRIEVE, RETRIEVE)
        self._writable = catalog.has_operation(STORE, STORE)

    @property
    def capabilities(self) -> MemoryCapabilities:
        return MemoryCapabilities(readable=self._readable, writable=self._writable,
                                  details={"readable": self._readable, "writable": self._writable})

    @property
    def readable(self) -> bool:
        return self._readable

    @property
    def writable(self) -> bool:
        return self._writable

    def _request(self, tool_id: str, request_id: str, arguments: dict[str, Any],
                 confirmation: str | None = None) -> ToolRequest:
        level = self._gateway.catalog.authorization_level(tool_id)
        return ToolRequest(
            request_id=request_id,
            tool_name=tool_id,
            operation=tool_id,
            authorization_level=level,
            arguments=arguments,
            originating_subsystem="agent.memory",
            confirmation_token=confirmation,
        )

    def retrieve(self, text: str, request_id: str, limit: int = MAX_RETURNED_HITS) -> MemoryQueryResult:
        if not self._readable:
            return MemoryQueryResult(available=False)
        query = str(text)[:MAX_QUERY_CHARS]
        if not query.strip():
            return MemoryQueryResult(available=False)
        bounded_limit = max(1, min(int(limit), MAX_RETURNED_HITS))
        result = self._gateway.execute(self._request(RETRIEVE, request_id, {"text": query, "limit": bounded_limit}))
        if not result.success:
            return MemoryQueryResult(available=False)
        hits = result.data.get("hits") if isinstance(result.data, dict) else None
        if not isinstance(hits, list):
            return MemoryQueryResult(available=True, hits=())
        return MemoryQueryResult(available=True, hits=tuple(hit for hit in hits[:bounded_limit] if isinstance(hit, dict)))

    def exists(self, text: str, request_id: str) -> bool | None:
        """True/False when memory is available; None when the answer is unknown."""
        result = self.retrieve(text, request_id, limit=1)
        if not result.available:
            return None
        return bool(result.hits)

    def store(self, content: str, memory_type: str, request_id: str,
              confirmation: str | None = None) -> MemoryWriteResult:
        if not self._writable:
            return MemoryWriteResult(accepted=False, reason="memory storage is unavailable")
        payload = str(content)[:MAX_CONTENT_CHARS]
        if not payload.strip():
            return MemoryWriteResult(accepted=False, reason="empty memory content")
        try:
            request = self._request(STORE, request_id, {"content": payload, "memory_type": memory_type},
                                    confirmation=confirmation)
            result = self._gateway.execute(request)
        except AgentError as error:
            return MemoryWriteResult(accepted=False, reason=error.code)
        if result.code.value == "confirmation_required":
            return MemoryWriteResult(accepted=False, pending_confirmation=True,
                                     reason="confirmation required for memory storage")
        if not result.success:
            return MemoryWriteResult(accepted=False, reason="memory storage rejected")
        memory_id = result.data.get("memory_id") if isinstance(result.data, dict) else None
        return MemoryWriteResult(accepted=True, memory_id=str(memory_id) if memory_id else None)

    def describe(self) -> dict[str, Any]:
        return self.capabilities.details
