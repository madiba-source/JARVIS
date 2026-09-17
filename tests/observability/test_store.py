import concurrent.futures

from app.observability.config import ObservabilityConfig
from app.observability.enums import EventType
from app.observability.events import StructuredEvent
from app.observability.store import SQLiteEventStore


def test_sqlite_concurrent_writers_and_retention(tmp_path) -> None:
    store = SQLiteEventStore(ObservabilityConfig(sqlite_path=tmp_path / "events.db", max_sqlite_rows=10))

    def write(index):
        return store.store_event(StructuredEvent(event_id=f"evt-{index}", event_type=EventType.TOOL_COMPLETED, component="test", source="writer"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(write, range(30)))
    assert len(store.query_events(100)) <= 10
    store.close()
