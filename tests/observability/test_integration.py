from app.core.events import EventBus
from app.core.lifecycle import JarvisCore
from app.observability.config import ObservabilityConfig
from app.observability.enums import EventType
from app.observability.events import StructuredEvent
from app.observability.integration import ObservabilityAdapter
from app.observability.logging import StructuredLogger
from app.observability.metrics import MetricsRegistry
from app.observability.store import SQLiteEventStore
from app.observability.tracing import NullTracer


def test_event_bus_observability_pipeline(tmp_path) -> None:
    config = ObservabilityConfig(log_directory=None, sqlite_path=tmp_path / "events.db")
    adapter = ObservabilityAdapter(StructuredLogger(config), MetricsRegistry(config), NullTracer(), SQLiteEventStore(config))
    bus = EventBus()
    adapter.attach(bus)
    bus.publish({"event_type": "SYSTEM_READY", "component": "core"})
    assert adapter.metrics.get_snapshot()["counters"]["observability_events_total{event_type=SYSTEM_READY}"] == 1
    assert len(adapter.store.query_events()) == 1
    adapter.store.close()


def test_core_lifecycle_publishes_to_attached_observer(tmp_path) -> None:
    config = ObservabilityConfig(log_directory=None, sqlite_path=tmp_path / "lifecycle.db")
    adapter = ObservabilityAdapter(StructuredLogger(config), MetricsRegistry(config), NullTracer(), SQLiteEventStore(config))
    core = JarvisCore()
    adapter.attach(core.event_bus)
    core.start()
    core.shutdown()
    assert adapter.metrics.get_snapshot()["counters"]["observability_events_total{event_type=SYSTEM_START}"] == 1
    assert adapter.metrics.get_snapshot()["counters"]["observability_events_total{event_type=SYSTEM_READY}"] == 1
    adapter.store.close()
