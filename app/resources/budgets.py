"""Finite execution budgets for future resource-aware work."""

from pydantic import BaseModel, ConfigDict, Field


class ExecutionBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_seconds: float = Field(default=60, gt=0)
    tool_calls: int = Field(default=0, ge=0)
    agent_steps: int = Field(default=0, ge=0)
    network_bytes: int = Field(default=0, ge=0)
    download_bytes: int = Field(default=0, ge=0)
