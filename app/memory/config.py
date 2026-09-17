"""Finite, validated limits; no network or background work on import."""

from pydantic import Field, model_validator

from .models import Schema


class MemoryConfig(Schema):
    max_memory_chars: int = Field(default=8192, ge=128, le=8192)
    max_metadata_bytes: int = Field(default=4096, ge=256, le=8192)
    max_records: int = Field(default=10000, ge=1, le=100000)
    max_versions: int = Field(default=16, ge=1, le=100)
    max_relationships: int = Field(default=32, ge=1, le=128)
    max_working_records: int = Field(default=32, ge=1, le=256)
    working_ttl_seconds: int = Field(default=1800, ge=1, le=86400)
    conversation_ttl_seconds: int = Field(default=604800, ge=60, le=2592000)
    max_document_bytes: int = Field(default=16384, ge=256, le=16384)
    max_chunks: int = Field(default=32, ge=1, le=128)
    chunk_chars: int = Field(default=1500, ge=128, le=8192)
    chunk_overlap: int = Field(default=150, ge=0, le=1024)
    max_embedding_batch: int = Field(default=8, ge=1, le=32)
    max_candidates: int = Field(default=64, ge=8, le=256)
    max_context_chars: int = Field(default=12000, ge=1024, le=32768)
    max_transfer_bytes: int = Field(default=1048576, ge=1024, le=8388608)
    max_transfer_records: int = Field(default=128, ge=1, le=512)
    max_operations_per_minute: int = Field(default=120, ge=1, le=1000)
    max_concurrent_operations: int = Field(default=4, ge=1, le=8)
    max_concurrent_index_jobs: int = Field(default=1, ge=1, le=1)
    index_batch: int = Field(default=16, ge=1, le=64)
    index_attempts: int = Field(default=3, ge=1, le=5)
    provider_timeout_seconds: float = Field(default=5, ge=0.1, le=30)
    dense_threshold: float = Field(default=0.35, ge=0.1, le=1)

    @model_validator(mode="after")
    def consistent(self) -> "MemoryConfig":
        if self.chunk_overlap >= self.chunk_chars or self.chunk_chars > self.max_memory_chars:
            raise ValueError("invalid chunk bounds")
        return self