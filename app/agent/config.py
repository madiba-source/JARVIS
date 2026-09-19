"""Validated agent admission limits.

These are admission controls, not operating-system enforcement. Python
bookkeeping can refuse to *start* work; it cannot promise a CPU percentage,
a memory ceiling or an interruptible callback. Any claim that a limit is
enforced rather than admitted is made explicitly where it is true.
"""

from pydantic import Field, StrictBool, model_validator

from .models import Schema


class AgentConfig(Schema):
    # --- global control -------------------------------------------------
    enabled: StrictBool = True
    cloud_enabled: StrictBool = False
    memory_persistence_enabled: StrictBool = True

    # --- plan shape -----------------------------------------------------
    max_plan_steps: int = Field(default=8, strict=True, ge=1, le=16)
    max_total_steps: int = Field(default=64, strict=True, ge=1, le=256)
    max_replans: int = Field(default=1, strict=True, ge=0, le=3)
    max_side_effects: int = Field(default=4, strict=True, ge=1, le=16)
    max_observations: int = Field(default=32, strict=True, ge=1, le=64)
    max_messages: int = Field(default=64, strict=True, ge=1, le=256)
    max_identical_failures: int = Field(default=2, strict=True, ge=1, le=4)

    # --- concurrency ----------------------------------------------------
    max_parallel_steps: int = Field(default=1, strict=True, ge=1, le=4)
    max_parallel_model_calls: int = Field(default=1, strict=True, ge=1, le=1)
    max_active_agents: int = Field(default=1, strict=True, ge=1, le=1)
    max_agent_depth: int = Field(default=1, strict=True, ge=1, le=1)
    parallel_join_timeout_seconds: float = Field(default=30, strict=True, ge=1, le=120)

    # --- retries --------------------------------------------------------
    max_retries: int = Field(default=2, strict=True, ge=0, le=2)
    retry_backoff_seconds: float = Field(default=0.05, strict=True, ge=0, le=5)
    retry_backoff_ceiling_seconds: float = Field(default=1, strict=True, ge=0, le=5)

    # --- time -----------------------------------------------------------
    max_runtime_seconds: float = Field(default=120, strict=True, ge=1, le=600)
    max_step_seconds: float = Field(default=30, strict=True, ge=1, le=120)
    model_timeout_seconds: float = Field(default=30, strict=True, ge=1, le=120)
    max_model_attempts: int = Field(default=1, strict=True, ge=1, le=2)
    queue_wait_seconds: float = Field(default=30, strict=True, ge=0.1, le=300)
    shutdown_timeout_seconds: float = Field(default=2, strict=True, ge=0.1, le=10)

    # --- bytes ----------------------------------------------------------
    max_output_bytes: int = Field(default=8192, strict=True, ge=512, le=8192)
    max_context_bytes: int = Field(default=16384, strict=True, ge=4096, le=32768)
    max_model_output_tokens: int = Field(default=1024, strict=True, ge=64, le=2048)
    max_model_output_bytes: int = Field(default=16384, strict=True, ge=1024, le=32768)

    # --- capacity -------------------------------------------------------
    queue_capacity: int = Field(default=8, strict=True, ge=1, le=32)
    max_sessions: int = Field(default=16, strict=True, ge=1, le=64)
    max_retained_requests: int = Field(default=32, strict=True, ge=1, le=128)
    max_session_requests: int = Field(default=32, strict=True, ge=1, le=128)

    @model_validator(mode="after")
    def consistent(self) -> "AgentConfig":
        if self.max_plan_steps > self.max_total_steps:
            raise ValueError("plan step limit exceeds total step budget")
        if self.retry_backoff_ceiling_seconds < self.retry_backoff_seconds:
            raise ValueError("retry backoff ceiling below base delay")
        if self.parallel_join_timeout_seconds > self.max_runtime_seconds:
            raise ValueError("parallel join timeout exceeds runtime budget")
        return self
