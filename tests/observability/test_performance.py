import pytest

from app.observability import PerformanceBudget, PerformanceRecorder, TelemetryMode


def test_performance_measurement_is_bounded_and_correlated():
    recorder = PerformanceRecorder(budget=PerformanceBudget(max_samples_per_operation=2, max_operations=1))
    with recorder.measure("startup", correlation={"request_id": "req", "password": "secret"}):
        pass
    with recorder.measure("startup"):
        pass
    with recorder.measure("other"):
        pass
    assert len(recorder.samples["startup"]) == 2
    assert "password" not in str(recorder.samples)
    assert "other" not in recorder.samples


def test_off_mode_has_no_overhead_records():
    recorder = PerformanceRecorder(mode=TelemetryMode.OFF)
    with recorder.measure("request") as result:
        assert result == {}
    assert recorder.samples == {}


def test_operation_names_and_budgets_are_bounded():
    with pytest.raises(ValueError):
        PerformanceRecorder(budget=PerformanceBudget(max_operations=0))
    recorder = PerformanceRecorder()
    with pytest.raises(ValueError, match="operation"):
        with recorder.measure("arbitrary label with user text"):
            pass


def test_disable_stops_future_measurements():
    recorder = PerformanceRecorder()
    recorder.disable()
    with recorder.measure("request"):
        pass
    assert recorder.samples == {}
