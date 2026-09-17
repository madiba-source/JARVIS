import pytest

from app.observability.config import ObservabilityConfig
from app.observability.metrics import MetricsRegistry


def test_metric_cardinality_is_bounded() -> None:
    metrics = MetricsRegistry(ObservabilityConfig(max_metric_series=2))
    metrics.increment_counter("requests_total", labels={"component": "a"})
    metrics.increment_counter("requests_total", labels={"component": "b"})
    with pytest.raises(ValueError):
        metrics.increment_counter("requests_total", labels={"component": "c"})
    assert metrics.series_count == 2


def test_metric_names_labels_and_values_are_validated() -> None:
    metrics = MetricsRegistry()
    with pytest.raises(ValueError): metrics.increment_counter("bad-name")
    with pytest.raises(ValueError): metrics.increment_counter("ok", labels={"a": "x", "b": "y", "c": "z", "d": "q", "e": "too-many"})
    with pytest.raises(ValueError): metrics.set_gauge("gauge", float("inf"))
