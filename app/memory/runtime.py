"""Explicit application composition; failure leaves a usable no-memory runtime."""

from pathlib import Path

from app.core.events import EventBus
from app.database.config import DatabaseConfig
from app.database.service import DatabaseService

from .config import MemoryConfig
from .context import AssembledContext, ContextAssembler, ContextMessage
from .migration import MEMORY_MIGRATIONS
from .models import Query, Scope
from .service import MemoryService
from .store import MemoryStore


class MemoryRuntime:
    def __init__(self, data_dir: Path, config: MemoryConfig, bus: EventBus,
                 vector_enabled: bool = False) -> None:
        self.service: MemoryService | None = None
        self.available = False
        self.vector_available = False
        try:
            database = DatabaseService(
                DatabaseConfig(db_path=str(data_dir / "jarvis.db"),
                               backup_directory=str(data_dir / "backups")),
                extension_migrations=MEMORY_MIGRATIONS,
            )
            database.initialize()
            self.service = MemoryService(MemoryStore(database, config), bus)
            self.available = True
            if vector_enabled:
                from .embeddings import OllamaMiniLM
                from .index import QdrantIndex
                provider = OllamaMiniLM(config)
                try:
                    self.service.indexer = QdrantIndex(provider, self.service.store,
                                                       data_dir / "qdrant", self.service.emit)
                    self.vector_available = True
                except Exception:
                    provider.close()
                    self.service.emit("dense_unavailable", success=False)
        except Exception:
            # No exception content, database path or SQL in model-visible status.
            self.available = False

    def context(self, scope: Scope, task: str, query: Query) -> AssembledContext:
        if self.service is not None and self.available:
            return ContextAssembler(self.service, scope).assemble(task, query)
        if not task.strip() or len(task) > 4096:
            raise ValueError("task size limit")
        messages = (
            ContextMessage(role="system", content=ContextAssembler.INSTRUCTIONS),
            ContextMessage(role="user", content=task),
            ContextMessage(role="user", content='{"label":"UNTRUSTED_CONTEXT_DATA","memory_available":false}'),
        )
        return AssembledContext(messages=messages, memory_available=False,
                                characters=sum(len(item.content) for item in messages))

    def close(self) -> None:
        if self.service is not None:
            self.service.close()
        self.available = self.vector_available = False