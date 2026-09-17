import logging

from app.observability.config import ObservabilityConfig
from app.observability.enums import EventType
from app.observability.events import StructuredEvent
from app.observability.logging import StructuredLogger


class FailingHandler(logging.Handler):
    def emit(self, record):
        raise RuntimeError("sink failed")


def test_handler_failure_isolated_and_counted() -> None:
    logger = StructuredLogger(ObservabilityConfig(console_logging=False, log_directory=None), handlers=[FailingHandler()])
    assert logger.emit(StructuredEvent(event_type=EventType.SYSTEM_ERROR, component="test", source="failure")) is False
    assert logger.dropped_events_count == 1


def test_logger_instances_do_not_clear_each_other(tmp_path) -> None:
    first = StructuredLogger(ObservabilityConfig(log_directory=tmp_path / "one", console_logging=False))
    second = StructuredLogger(ObservabilityConfig(log_directory=tmp_path / "two", console_logging=False))
    assert first.handler_count == 1 and second.handler_count == 1
