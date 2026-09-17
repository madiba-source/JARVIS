import json
import sqlite3

import pytest

from app.observability.config import ObservabilityConfig
from app.observability.enums import EventType
from app.observability.events import StructuredEvent
from app.observability.redaction import CYCLE_PLACEHOLDER, REDACTED_PLACEHOLDER, redact_sensitive_data
from app.observability.store import SQLiteEventStore


def event(metadata=None):
    return StructuredEvent(event_type=EventType.REQUEST_RECEIVED, component="test", source="security", metadata=metadata or {})


def test_sqlite_redacts_nested_secrets(tmp_path) -> None:
    store = SQLiteEventStore(ObservabilityConfig(sqlite_path=tmp_path / "events.db"))
    secret = "hunter2"
    assert store.store_event(event({"nested": {"password": secret}, "items": [{"api_key": "abc"}]}))
    raw = sqlite3.connect(tmp_path / "events.db").execute("SELECT payload FROM events").fetchone()[0]
    assert secret not in raw and "abc" not in raw
    assert REDACTED_PLACEHOLDER in raw
    store.close()


def test_event_metadata_is_deeply_immutable() -> None:
    metadata = {"nested": {"items": ["safe"]}}
    record = event(metadata)
    metadata["nested"]["items"].append("changed")
    assert list(record.metadata["nested"]["items"]) == ["safe"]
    with pytest.raises(TypeError):
        record.metadata["nested"]["x"] = "blocked"


def test_circular_dict_and_list_terminate() -> None:
    mapping = {}
    mapping["self"] = mapping
    values = []
    values.append(values)
    assert redact_sensitive_data(mapping)["self"] == CYCLE_PLACEHOLDER
    assert redact_sensitive_data(values)[0] == CYCLE_PLACEHOLDER
    assert event({"mapping": mapping})


def test_unsupported_keys_and_nonfinite_values_are_safe() -> None:
    result = redact_sensitive_data({1: "value", "number": float("nan")})
    assert "[UNSUPPORTED_KEY:int]" in result
    assert result["number"] == "[NON_FINITE_NUMBER]"
