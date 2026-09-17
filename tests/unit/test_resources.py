import pytest
from pydantic import ValidationError

from app.resources import ExecutionBudget, ResourceLimits, ResourceSnapshot, capture_snapshot


def test_resource_snapshot_creation() -> None:
    snapshot = ResourceSnapshot(memory_used_mb=100, process_count=2)
    assert snapshot.memory_used_mb == 100
    assert snapshot.temperatures_c == {}


def test_capture_snapshot_is_read_only_and_populated() -> None:
    snapshot = capture_snapshot()
    assert snapshot.disk_free_mb is not None
    assert snapshot.process_count is not None


def test_resource_limits_validate_bounds() -> None:
    assert ResourceLimits(max_memory_mb=1024, max_runtime_seconds=10).max_memory_mb == 1024
    with pytest.raises(ValidationError):
        ResourceLimits(max_memory_mb=0)


def test_execution_budget_rejects_unbounded_values() -> None:
    assert ExecutionBudget(runtime_seconds=5, tool_calls=2).tool_calls == 2
    with pytest.raises(ValidationError):
        ExecutionBudget(runtime_seconds=0)