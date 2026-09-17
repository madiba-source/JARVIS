"""Explicit text ingestion through the Phase 04 filesystem policy gateway."""

from pathlib import PurePosixPath
from uuid import NAMESPACE_URL, uuid4, uuid5

from .models import Candidate, MemoryType, Provenance, Scope, SourceKind, digest, now, reject_secrets
from .service import MemoryRejected, MemoryService
from .store import scope_key

from app.policy.enums import AuthorizationLevel
from app.policy.models import ToolRequest


class KnowledgeIngestor:
    EXTENSIONS = {".txt", ".md", ".py", ".js", ".ts", ".json", ".toml", ".yaml", ".yml", ".rst", ".csv"}
    FORBIDDEN = {"credentials", "secrets", "tokens", "cookies", "id_rsa", "id_ed25519"}

    def __init__(self, service: MemoryService, filesystem_gateway, scope: Scope) -> None:
        self._service, self._gateway, self._scope = service, filesystem_gateway, scope

    def ingest(self, path: str, *, approved: bool = False) -> tuple:
        if not approved:
            raise MemoryRejected("knowledge ingestion requires explicit approval")
        config = self._service.config
        parsed = PurePosixPath(path)
        if (len(path) > 512 or parsed.is_absolute() or ".." in parsed.parts
                or parsed.suffix.lower() not in self.EXTENSIONS
                or any(part.startswith(".") or any(word in part.casefold() for word in self.FORBIDDEN)
                       for part in parsed.parts)):
            raise MemoryRejected("unsupported or sensitive document path")
        request = ToolRequest(
            request_id=f"ingest-{uuid4()}", tool_name="filesystem", operation="read_file",
            authorization_level=AuthorizationLevel.L0_READ_ONLY,
            arguments={"path": path, "max_bytes": config.max_document_bytes},
            originating_subsystem="memory.ingestion",
        )
        result = self._gateway.execute(request)
        if not result.success or result.data.get("binary") or not result.stdout.strip():
            raise MemoryRejected("document read unavailable")
        text = result.stdout
        if len(text.encode("utf-8")) > config.max_document_bytes:
            raise MemoryRejected("document size limit")
        reject_secrets(text)
        document_hash = digest(text)
        document_id = digest(scope_key(self._scope) + ":" + str(parsed))
        source = Provenance(kind=SourceKind.FILE, source_id=document_id, source_timestamp=now(),
                            source_hash=document_hash, document_id=document_id)
        candidates = []
        offset = 0
        while offset < len(text):
            if len(candidates) >= config.max_chunks:
                raise MemoryRejected("document chunk limit")
            end = min(len(text), offset + config.chunk_chars)
            chunk = text[offset:end]
            if chunk.strip():
                candidate = Candidate(
                    content=chunk, memory_type=MemoryType.KNOWLEDGE, provenance=source,
                    offset_start=offset, offset_end=end,
                )
                self._service.validate(self._scope, candidate, True)
                identity = uuid5(NAMESPACE_URL, f"{document_id}:{document_hash}:{offset}:{end}")
                candidates.append((candidate, identity))
            if end == len(text):
                break
            offset = end - config.chunk_overlap
        # Full extraction/validation precedes writes. Storage failures may leave a
        # partial document; deterministic IDs make an explicitly retried job resumable.
        records = []
        for candidate, identity in candidates:
            records.append(self._service.capture(self._scope, candidate, approved=True, memory_id=identity))
        return tuple(records)