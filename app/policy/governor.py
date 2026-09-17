"""Phase 03 resource admission boundary.

This module validates admission only. Runtime CPU/RAM/process/time/network
 enforcement belongs to a later execution runtime that consumes the admission.
"""

import math
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field


class ResourceCheckResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    reason: str
    effective_budget: dict[str, float] = Field(default_factory=dict)


class DefaultResourceGovernor:
    vocabulary = frozenset({"memory_mb", "cpu_percent", "timeout_seconds", "process_count", "disk_mb", "network_mb"})

    def __init__(self, system_maximums: Mapping[str, float] | None = None) -> None:
        self.system_maximums = dict(system_maximums or {
            "memory_mb": 2048.0, "cpu_percent": 100.0, "timeout_seconds": 60.0,
            "process_count": 5.0, "disk_mb": 512.0, "network_mb": 100.0,
        })

    def check_budget(self, requested: Mapping[str, float] | None, tool_requirements: Mapping[str, float] | None = None) -> ResourceCheckResult:
        requested = dict(requested or {})
        requirements = dict(tool_requirements or {})
        for source in (requested, requirements, self.system_maximums):
            for key, value in source.items():
                if key not in self.vocabulary:
                    return ResourceCheckResult(allowed=False, reason=f"Unknown resource type: {key}")
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
                    return ResourceCheckResult(allowed=False, reason=f"Invalid resource value for {key}")
        for key, requirement in requirements.items():
            if requirement > self.system_maximums.get(key, 0):
                return ResourceCheckResult(allowed=False, reason=f"Tool requirement exceeds system maximum: {key}")
            if key in requested and requested[key] < requirement:
                return ResourceCheckResult(allowed=False, reason=f"Requested cap is below tool requirement: {key}")
        for key, value in requested.items():
            if value > self.system_maximums.get(key, 0):
                return ResourceCheckResult(allowed=False, reason=f"Requested resource cap exceeds system maximum: {key}")
        effective = {key: requirements.get(key, requested.get(key, maximum)) for key, maximum in self.system_maximums.items() if key in requirements or key in requested}
        if any(value > self.system_maximums[key] for key, value in effective.items()):
            return ResourceCheckResult(allowed=False, reason="Requested resource cap exceeds system maximum")
        return ResourceCheckResult(allowed=True, reason="Resource admission accepted", effective_budget=effective)
