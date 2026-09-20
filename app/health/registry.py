"""Deterministic component registry and dependency propagation."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import FailureCategory, HealthLevel, HealthRecord, HealthStatus, RecoveryState


@dataclass(frozen=True)
class ProbeResult:
    status: HealthStatus = HealthStatus.HEALTHY
    liveness: HealthStatus = HealthStatus.HEALTHY
    readiness: HealthStatus = HealthStatus.HEALTHY
    category: FailureCategory | None = None
    summary: str = ""
    resources: dict[str, float | str] | None = None


@dataclass(frozen=True)
class ComponentDefinition:
    component_id: str
    probe: Callable[[], ProbeResult]
    dependencies: tuple[str, ...] = ()
    level: HealthLevel = HealthLevel.SUBSYSTEM
    version: str | None = None
    recovery_actions: tuple[str, ...] = ()


class HealthRegistry:
    def __init__(self, *, max_components: int = 32, max_history: int = 256) -> None:
        self.max_components = max_components
        self.max_history = max_history
        self._definitions: dict[str, ComponentDefinition] = {}
        self._records: dict[str, HealthRecord] = {}
        self._history: list[HealthRecord] = []

    @property
    def records(self) -> tuple[HealthRecord, ...]:
        return tuple(self._records.values())

    @property
    def history(self) -> tuple[HealthRecord, ...]:
        return tuple(self._history)

    def register(self, definition: ComponentDefinition) -> None:
        if not definition.component_id or len(definition.component_id) > 64 or not definition.component_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("invalid component identifier")
        if definition.component_id not in self._definitions and len(self._definitions) >= self.max_components:
            raise ValueError("component limit reached")
        if definition.component_id in definition.dependencies:
            raise ValueError("component cannot depend on itself")
        self._definitions[definition.component_id] = definition

    def check(self, component_id: str) -> HealthRecord:
        definition = self._definitions.get(component_id)
        if definition is None:
            raise KeyError("unknown component")
        started = time.monotonic()
        dependencies = tuple(self.check(dep) for dep in definition.dependencies)
        if any(record.status in {HealthStatus.FAILED, HealthStatus.DISABLED} or record.readiness in {HealthStatus.FAILED, HealthStatus.DISABLED} for record in dependencies):
            result = ProbeResult(HealthStatus.DEGRADED, HealthStatus.HEALTHY, HealthStatus.DEGRADED, FailureCategory.DEPENDENCY, "dependency is not ready")
        else:
            try:
                result = definition.probe()
                if not isinstance(result, ProbeResult):
                    raise TypeError("probe must return ProbeResult")
            except TimeoutError:
                result = ProbeResult(HealthStatus.FAILED, HealthStatus.FAILED, HealthStatus.FAILED, FailureCategory.TIMEOUT, "probe timed out")
            except Exception as error:
                result = ProbeResult(HealthStatus.FAILED, HealthStatus.FAILED, HealthStatus.FAILED, FailureCategory.UNKNOWN, type(error).__name__[:128])
        previous = self._records.get(component_id)
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        record = HealthRecord(component_id=component_id, status=result.status, timestamp=now, level=definition.level, liveness=result.liveness, readiness=result.readiness, version=definition.version, dependencies=definition.dependencies, latency_ms=round((time.monotonic() - started) * 1000, 3), resource_state=result.resources or {}, last_success_at=now if result.status == HealthStatus.HEALTHY else (previous.last_success_at if previous else None), failure_category=result.category, failure_summary=result.summary[:256], recovery_state=previous.recovery_state if previous else RecoveryState.NONE, recovery_action=previous.recovery_action if previous else None)
        self._records[component_id] = record
        self._history.append(record)
        del self._history[:-self.max_history]
        return record

    def check_all(self) -> tuple[HealthRecord, ...]:
        return tuple(self.check(component_id) for component_id in self._definitions)

    def definition(self, component_id: str) -> ComponentDefinition:
        try:
            return self._definitions[component_id]
        except KeyError:
            raise KeyError("unknown component") from None
