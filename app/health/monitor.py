"""Bounded health checks, explanations, and allow-listed recovery."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone

from .models import FailureCategory, HealthLevel, HealthRecord, HealthStatus, RecoveryState
from .registry import ComponentDefinition, HealthRegistry, ProbeResult


class HealthMonitor:
    def __init__(self, *, event_bus=None, max_history: int = 256) -> None:
        self.registry = HealthRegistry(max_history=max_history)
        self.event_bus = event_bus
        self.enabled = True
        self._recoveries: dict[tuple[str, str], Callable[[], bool]] = {}
        self._recovery_attempts: dict[str, int] = {}
        self._max_recovery_attempts = 2

    def register(self, definition: ComponentDefinition) -> None:
        self.registry.register(definition)

    def register_component(self, component_id: str, probe: Callable[[], ProbeResult], *, dependencies: tuple[str, ...] = (), level: HealthLevel = HealthLevel.SUBSYSTEM, recovery_actions: tuple[str, ...] = ()) -> None:
        self.register(ComponentDefinition(component_id, probe, dependencies, level, recovery_actions=recovery_actions))

    def add_recovery(self, component_id: str, action_id: str, action: Callable[[], bool]) -> None:
        if not action_id or not action_id.replace("_", "").isalnum():
            raise ValueError("invalid recovery identifier")
        if action_id not in self.registry.definition(component_id).recovery_actions:
            raise ValueError("recovery action is not allow-listed")
        self._recoveries[(component_id, action_id)] = action

    def check(self) -> tuple[HealthRecord, ...]:
        if not self.enabled:
            return tuple(replace(record, status=HealthStatus.DISABLED, liveness=HealthStatus.DISABLED, readiness=HealthStatus.DISABLED) for record in self.registry.records)
        records = self.registry.check_all()
        for record in records:
            if self.event_bus is not None and (not self.registry.history or len(self.registry.history) < 2 or self.registry.history[-2].status != record.status):
                self.event_bus.publish({"event_type": "HEALTH_CHANGED", "component": record.component_id, "status": record.status.value})
        return records

    def recover(self, component_id: str, action_id: str) -> HealthRecord:
        if not self.enabled:
            raise RuntimeError("health monitoring disabled")
        key = (component_id, action_id)
        action = self._recoveries.get(key)
        if action is None:
            raise ValueError("recovery action is not available")
        attempts = self._recovery_attempts.get(component_id, 0)
        if attempts >= self._max_recovery_attempts:
            raise RuntimeError("recovery retry limit exhausted")
        self._recovery_attempts[component_id] = attempts + 1
        current = self.registry._records.get(component_id)
        if current is None:
            raise KeyError("unknown component")
        self.registry._records[component_id] = replace(current, status=HealthStatus.RECOVERING, recovery_state=RecoveryState.ATTEMPTED, recovery_action=action_id)
        try:
            succeeded = bool(action())
        except Exception:
            succeeded = False
        record = self.registry.check(component_id)
        state = RecoveryState.SUCCEEDED if succeeded and record.status == HealthStatus.HEALTHY else RecoveryState.FAILED
        updated = replace(record, recovery_state=state, recovery_action=action_id)
        self.registry._records[component_id] = updated
        return updated

    def diagnostic(self) -> dict[str, object]:
        records = self.check()
        return {"overall": "failed" if any(item.status == HealthStatus.FAILED for item in records) else "degraded" if any(item.status in {HealthStatus.DEGRADED, HealthStatus.UNKNOWN} for item in records) else "healthy", "components": {item.component_id: item.public() for item in records}}

    def explain(self, component_id: str | None = None) -> tuple[dict[str, object], ...]:
        records = self.registry.records
        if component_id:
            records = tuple(item for item in records if item.component_id == component_id)
        return tuple({"component": item.component_id, "status": item.status.value, "failure": item.failure_summary, "category": item.failure_category.value if item.failure_category else None, "dependencies": item.dependencies, "last_success": item.last_success_at.isoformat() if item.last_success_at else None, "recovery": item.recovery_state.value} for item in records if item.status != HealthStatus.HEALTHY)

    def disable(self) -> None:
        self.enabled = False

    def enable(self) -> None:
        self.enabled = True

    @staticmethod
    def resource_probe(*, disk_path: str = ".", min_disk_free_mb: int = 256) -> ProbeResult:
        try:
            usage = shutil.disk_usage(disk_path)
            free_mb = usage.free / (1024 * 1024)
            resources = {"disk_free_mb": round(free_mb, 2), "process_id": float(os.getpid())}
            if free_mb < min_disk_free_mb:
                return ProbeResult(HealthStatus.DEGRADED, resources=resources, category=FailureCategory.RESOURCE, summary="disk free space below configured threshold")
            return ProbeResult(resources=resources)
        except OSError as error:
            return ProbeResult(HealthStatus.FAILED, HealthStatus.FAILED, HealthStatus.FAILED, FailureCategory.STORAGE, type(error).__name__)

    @staticmethod
    def healthy_probe() -> ProbeResult:
        return ProbeResult()
