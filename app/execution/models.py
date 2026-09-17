"""Typed execution results and bounded runtime limits."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExecutionCode(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    INVALID_REQUEST = "invalid_request"
    CONFIRMATION_REQUIRED = "confirmation_required"
    TIMEOUT = "timeout"
    RESOURCE_LIMIT = "resource_limit"
    EXECUTION_FAILED = "execution_failed"
    VERIFICATION_FAILED = "verification_failed"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"


class ExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ExecutionCode
    message: str = Field(max_length=1024)
    data: dict[str, Any] = Field(default_factory=dict)
    stdout: str = Field(default="", max_length=16_384)
    stderr: str = Field(default="", max_length=16_384)
    exit_code: int | None = None

    @property
    def success(self) -> bool:
        return self.code is ExecutionCode.SUCCESS


class ExecutionLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_concurrent_operations: int = Field(default=4, ge=1, le=32)
    command_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    max_stdout_bytes: int = Field(default=16_384, ge=1, le=1_048_576)
    max_stderr_bytes: int = Field(default=16_384, ge=1, le=1_048_576)
    max_file_read_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)
    max_file_write_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)
    max_directory_entries: int = Field(default=1_000, ge=1, le=100_000)
    max_search_results: int = Field(default=1_000, ge=1, le=100_000)
