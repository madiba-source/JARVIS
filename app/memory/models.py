"""Immutable schemas at the memory trust boundary. Content is never authority."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def now() -> datetime:
    return datetime.now(timezone.utc)


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True, allow_inf_nan=False)


class MemoryType(StrEnum):
    WORKING = "working"
    CONVERSATION = "conversation"
    PROJECT = "project"
    PREFERENCE = "preference"
    KNOWLEDGE = "knowledge"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class Status(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    ARCHIVED = "archived"
    DELETED = "deleted"


class IndexStatus(StrEnum):
    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"
    STALE = "stale"


class SourceKind(StrEnum):
    USER = "user_statement"
    DERIVED = "assistant_derived"
    FILE = "file"
    DOCUMENT = "document"
    WEB = "web_source"
    APPLICATION = "application_event"
    SYSTEM = "system_event"
    IMPORT = "import"


class Sensitivity(StrEnum):
    NORMAL = "normal"
    PRIVATE = "private"


class Provenance(Schema):
    kind: SourceKind
    source_id: Identifier
    source_timestamp: datetime
    source_hash: Digest | None = None
    conversation_id: Identifier | None = None
    turn_refs: tuple[Identifier, ...] = Field(default=(), max_length=32)
    document_id: Identifier | None = None
    # These are attributed estimates, not a declaration of truth.
    source_authority: float = Field(default=0.5, ge=0, le=1)

    @field_validator("source_timestamp")
    @classmethod
    def timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or not 1970 <= value.year <= 2100:
            raise ValueError("timezone-aware timestamp in supported range required")
        if value > now():
            raise ValueError("source timestamp is in the future")
        return value.astimezone(timezone.utc)


class Scope(Schema):
    """Constructed by trusted application/session bootstrap, never by model output."""
    namespace: Identifier
    project_id: Identifier | None = None
    conversation_id: Identifier | None = None


class Candidate(Schema):
    content: str = Field(min_length=1, max_length=8192)
    memory_type: MemoryType
    provenance: Provenance
    tags: tuple[Identifier, ...] = Field(default=(), max_length=16)
    entities: tuple[Identifier, ...] = Field(default=(), max_length=16)
    extraction_confidence: float = Field(default=0.5, ge=0, le=1)
    importance: float = Field(default=0.5, ge=0, le=1)
    sensitivity: Sensitivity = Sensitivity.NORMAL
    valid_from: datetime = Field(default_factory=now)
    valid_until: datetime | None = None
    fact_key: Identifier | None = None
    offset_start: int | None = Field(default=None, ge=0, le=1_000_000)
    offset_end: int | None = Field(default=None, ge=0, le=1_000_000)

    @field_validator("content")
    @classmethod
    def safe_text(cls, value: str) -> str:
        if not normalize(value):
            raise ValueError("empty normalized content")
        if any(unicodedata.category(c) in {"Cs", "Cc"} and c not in "\n\r\t" for c in value):
            raise ValueError("invalid text controls")
        if len(value.encode("utf-8")) > 32768:
            raise ValueError("encoded content limit")
        return value

    @field_validator("valid_from", "valid_until")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or not 1970 <= value.year <= 2100):
            raise ValueError("invalid timestamp")
        return value.astimezone(timezone.utc) if value is not None else None

    @model_validator(mode="after")
    def interval(self) -> Candidate:
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("invalid validity interval")
        if (self.offset_start is None) != (self.offset_end is None):
            raise ValueError("both offsets required")
        if self.offset_start is not None and self.offset_end <= self.offset_start:
            raise ValueError("invalid offsets")
        return self


class MemoryRecord(Candidate):
    memory_id: UUID = Field(default_factory=uuid4)
    scope: Scope
    normalized_content: str = Field(max_length=8192)
    content_hash: Digest
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    last_accessed_at: datetime | None = None
    status: Status = Status.ACTIVE
    version: int = Field(default=1, ge=1, le=1000)
    index_status: IndexStatus = IndexStatus.PENDING

    @model_validator(mode="after")
    def integrity(self) -> MemoryRecord:
        if self.normalized_content != normalize(self.content) or self.content_hash != digest(self.normalized_content):
            raise ValueError("content integrity mismatch")
        for value in (self.created_at, self.updated_at, self.last_accessed_at):
            if value is not None and (value.tzinfo is None or not 1970 <= value.year <= 2100):
                raise ValueError("invalid record timestamp")
        if self.updated_at < self.created_at:
            raise ValueError("updated before creation")
        return self


class Query(Schema):
    text: str = Field(min_length=1, max_length=512)
    types: tuple[MemoryType, ...] = Field(default=(), max_length=8)
    tags: tuple[Identifier, ...] = Field(default=(), max_length=16)
    source_id: Identifier | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = Field(default=5, ge=1, le=32)

    @model_validator(mode="after")
    def dates(self) -> Query:
        for value in (self.since, self.until):
            if value is not None and (value.tzinfo is None or not 1970 <= value.year <= 2100):
                raise ValueError("invalid query timestamp")
        if self.since and self.until and self.since > self.until:
            raise ValueError("invalid query interval")
        Candidate.safe_text(self.text)
        return self


class Signals(Schema):
    lexical: float = Field(ge=0, le=1)
    dense: float = Field(ge=0, le=1)
    recency: float = Field(ge=0, le=1)
    importance: float = Field(ge=0, le=1)
    extraction_confidence: float = Field(ge=0, le=1)
    source_authority: float = Field(ge=0, le=1)
    score: float = Field(ge=0, le=1)


class Hit(Schema):
    record: MemoryRecord
    signals: Signals


class Retrieval(Schema):
    hits: tuple[Hit, ...] = Field(default=(), max_length=32)
    available: bool = True
    dense_available: bool = False
    candidates: int = Field(default=0, ge=0)
    duration_ms: float = Field(default=0, ge=0)


class RelationKind(StrEnum):
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"
    DERIVED_FROM = "derived_from"
    REFERENCES = "references"
    RELATED_TO = "related_to"


class Relationship(Schema):
    source: UUID
    target: UUID
    kind: RelationKind

    @model_validator(mode="after")
    def distinct(self) -> Relationship:
        if self.source == self.target:
            raise ValueError("self relationship rejected")
        return self


SECRET = re.compile(
    r"(?i)(?:password|passwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|"
    r"client[_ -]?secret|authorization|cookie|session[_ -]?(?:id|key|token))\s*[:=]\s*\S+"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b"
    r"|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
)


def reject_secrets(text: str) -> None:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(c for c in normalized if unicodedata.category(c) != "Cf")
    if SECRET.search(normalized):
        raise ValueError("sensitive-looking content rejected")