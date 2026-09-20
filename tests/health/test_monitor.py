import pytest

from app.health import FailureCategory, HealthMonitor, HealthStatus
from app.health.registry import ComponentDefinition, ProbeResult


def test_dependency_failure_propagates_to_readiness():
    monitor = HealthMonitor()
    monitor.register_component("local_model", lambda: ProbeResult(HealthStatus.FAILED, HealthStatus.FAILED, HealthStatus.FAILED, FailureCategory.MODEL, "model unavailable"))
    monitor.register_component("agent", HealthMonitor.healthy_probe, dependencies=("local_model",))
    record = monitor.check()[1]
    assert record.status is HealthStatus.DEGRADED
    assert record.readiness is HealthStatus.DEGRADED
    assert record.failure_category is FailureCategory.DEPENDENCY


def test_diagnostic_and_history_are_bounded_and_secret_free():
    monitor = HealthMonitor(max_history=2)
    monitor.register_component("database", lambda: ProbeResult(HealthStatus.FAILED, HealthStatus.FAILED, HealthStatus.FAILED, FailureCategory.STORAGE, "password=hidden"))
    monitor.check()
    monitor.check()
    monitor.check()
    assert len(monitor.registry.history) == 2
    assert "hidden" not in str(monitor.diagnostic())


def test_recovery_requires_allowlisted_action_and_is_bounded():
    state = {"healthy": False}
    monitor = HealthMonitor()
    monitor.register(ComponentDefinition("worker", lambda: ProbeResult() if state["healthy"] else ProbeResult(HealthStatus.FAILED), recovery_actions=("restart_worker",)))
    monitor.check()
    with pytest.raises(ValueError, match="allow-listed"):
        monitor.add_recovery("worker", "run_shell", lambda: True)
    monitor.add_recovery("worker", "restart_worker", lambda: state.update(healthy=True) is None)
    assert monitor.recover("worker", "restart_worker").status is HealthStatus.HEALTHY


def test_disable_stops_probes_and_recovery():
    calls = []
    monitor = HealthMonitor()
    monitor.register_component("worker", lambda: calls.append(True) or ProbeResult())
    monitor.check()
    monitor.disable()
    monitor.check()
    assert len(calls) == 1
    with pytest.raises(RuntimeError, match="disabled"):
        monitor.recover("worker", "restart")


def test_resource_probe_is_read_only_and_bounded():
    result = HealthMonitor.resource_probe(min_disk_free_mb=0)
    assert result.status is HealthStatus.HEALTHY
    assert "disk_free_mb" in result.resources
