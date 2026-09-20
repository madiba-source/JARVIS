"""Typed, secret-free health and recovery records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4
import re


class HealthStatus(StrEnum):
    UNKNOWN = "unknown"
    CHECKING = "checking"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    DISABLED = "disabled"
    RECOVERING = "recovering"


class HealthLevel(StrEnum):
    PROCESS = "l0_process"
    SUBSYSTEM = "l1_subsystem"
    DEPENDENCY = "l2_dependency"
    FUNCTIONAL = "l3_functional"
    RESOURCE = "l4_resource"
    SECURITY = "l5_security"


class FailureCategory(StrEnum):
    CONFIGURATION = "configuration"
    DEPENDENCY = "dependency"
    RESOURCE = "resource"
    TIMEOUT = "timeout"
    NETWORK = "network"
    MODEL = "model"
    AUDIO = "audio"
    VISION = "vision"
    STORAGE = "storage"
    PERMISSION = "permission"
    POLICY = "policy"
    BUG = "bug"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class RecoveryState(StrEnum):
    NONE = "none"
    AVAILABLE = "available"
    ATTEMPTED = "attempted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True)
class HealthRecord:
    component_id: str
    status: HealthStatus
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    level: HealthLevel = HealthLevel.SUBSYSTEM
    liveness: HealthStatus = HealthStatus.UNKNOWN
    readiness: HealthStatus = HealthStatus.UNKNOWN
    version: str | None = None
    dependencies: tuple[str, ...] = ()
    latency_ms: float | None = None
    resource_state: dict[str, float | str] = field(default_factory=dict)
    last_success_at: datetime | None = None
    failure_category: FailureCategory | None = None
    failure_summary: str = ""
    recovery_state: RecoveryState = RecoveryState.NONE
    recovery_action: str | None = None
    record_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        safe = re.sub(r"(?i)(password|token|secret|api[_ -]?key)\s*[:=]\s*\S+", r"\1=[redacted]", self.failure_summary)
        object.__setattr__(self, "failure_summary", safe[:256])

    def public(self) -> dict[str, object]:
        return {
            "component_id": self.component_id,
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.value,
            "liveness": self.liveness.value,
            "readiness": self.readiness.value,
            "version": self.version,
            "dependencies": self.dependencies,
            "latency_ms": self.latency_ms,
            "resource_state": dict(self.resource_state),
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "failure_category": self.failure_category.value if self.failure_category else None,
            "failure_summary": self.failure_summary,
            "recovery_state": self.recovery_state.value,
            "recovery_action": self.recovery_action,
        }
