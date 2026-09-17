"""Failure-isolated structured JSON logging."""

from __future__ import annotations

import json
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from .config import ObservabilityConfig
from .events import StructuredEvent
from .redaction import redact_sensitive_data


class StructuredLogger:
    def __init__(self, config: ObservabilityConfig | None = None, handlers: list[logging.Handler] | None = None) -> None:
        self.config = config or ObservabilityConfig()
        self._logger = logging.Logger(f"jarvis_observability_{id(self)}")
        self._logger.setLevel(getattr(logging, self.config.log_level.upper(), logging.INFO))
        self._logger.propagate = False
        self._lock = threading.Lock()
        self._dropped = 0
        formatter = logging.Formatter("%(message)s")
        for handler in handlers or self._build_handlers():
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)

    def _build_handlers(self) -> list[logging.Handler]:
        handlers: list[logging.Handler] = []
        if self.config.console_logging:
            handlers.append(logging.StreamHandler(sys.stdout))
        if self.config.log_directory:
            self.config.log_directory.mkdir(parents=True, exist_ok=True)
            handlers.append(RotatingFileHandler(self.config.log_directory / "jarvis.log", maxBytes=self.config.max_log_size_bytes, backupCount=self.config.backup_count, encoding="utf-8"))
        return handlers

    def emit(self, event: StructuredEvent, safe_payload: dict[str, Any] | None = None) -> bool:
        try:
            payload = safe_payload if safe_payload is not None else redact_sensitive_data(event_to_dict(event))
            encoded = json.dumps(payload, sort_keys=True, default=str, allow_nan=False)
            if len(encoded.encode()) > self.config.max_event_payload_bytes:
                raise ValueError("event payload exceeds configured maximum")
            self._logger.log(getattr(logging, event.severity.value, logging.INFO), encoded)
            return True
        except Exception as error:
            with self._lock:
                self._dropped += 1
            try:
                sys.stderr.write(f"[OBSERVABILITY_FAILURE] {type(error).__name__}\n")
            except Exception:
                pass
            return False

    @property
    def dropped_events_count(self) -> int:
        with self._lock:
            return self._dropped

    @property
    def handler_count(self) -> int:
        return len(self._logger.handlers)


def event_to_dict(event: StructuredEvent) -> dict[str, Any]:
    return {
        key: value for key, value in {
            "event_id": event.event_id, "timestamp": event.timestamp.isoformat(), "monotonic_timestamp": event.monotonic_timestamp,
            "event_type": event.event_type.value, "severity": event.severity.value, "component": event.component, "source": event.source,
            "request_id": event.request_id, "session_id": event.session_id, "trace_id": event.trace_id, "span_id": event.span_id,
            "operation": event.operation, "authorization_level": event.authorization_level, "tool_id": event.tool_id,
            "duration_ms": event.duration_ms, "success": event.success, "error_type": event.error_type, "error_message": event.error_message,
            "metadata": event.metadata,
        }.items() if value is not None
    }


_global_logger: StructuredLogger | None = None
_global_lock = threading.Lock()


def get_global_logger() -> StructuredLogger:
    global _global_logger
    with _global_lock:
        if _global_logger is None:
            _global_logger = StructuredLogger()
        return _global_logger


def set_global_logger(logger: StructuredLogger) -> None:
    global _global_logger
    with _global_lock:
        _global_logger = logger
