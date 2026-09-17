"""Validated resource limits used by bounded experiments."""

from pydantic import BaseModel, ConfigDict, Field


class ResourceLimits(BaseModel):
    """Advisory limits; callers must stop work when a limit is exceeded."""

    model_config = ConfigDict(extra="forbid")

    max_cpu_percent: float | None = Field(default=None, ge=0, le=100)
    max_memory_mb: int | None = Field(default=None, ge=1)
    max_swap_mb: int | None = Field(default=None, ge=0)
    max_disk_free_mb: int | None = Field(default=None, ge=0)
    max_processes: int | None = Field(default=None, ge=1)
    max_runtime_seconds: float = Field(default=120, gt=0)
    max_tool_calls: int = Field(default=0, ge=0)
    max_agent_steps: int = Field(default=0, ge=0)
    max_network_bytes: int = Field(default=0, ge=0)
    max_download_bytes: int = Field(default=0, ge=0)