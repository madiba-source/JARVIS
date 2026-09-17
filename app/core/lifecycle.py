"""Minimal, explicit JARVIS lifecycle for foundation validation."""

import logging

from .config import Settings
from .events import EventBus


class JarvisCore:
    """Owns only startup and shutdown state during Phase 01."""

    def __init__(self, settings: Settings | None = None, event_bus: EventBus | None = None) -> None:
        self.settings = settings or Settings()
        self.event_bus = event_bus or EventBus()
        self._started = False
        self._logger = logging.getLogger("jarvis.core")

    @property
    def is_running(self) -> bool:
        return self._started

    def start(self) -> None:
        if self._started:
            return
        self._logger.info("JARVIS starting", extra={"environment": self.settings.environment})
        self.event_bus.publish({"event_type": "SYSTEM_START", "component": "core"})
        self._logger.info("JARVIS environment", extra={"ollama_host": self.settings.ollama_host})
        self._started = True
        self._logger.info("JARVIS ready")
        self.event_bus.publish({"event_type": "SYSTEM_READY", "component": "core"})

    def shutdown(self) -> None:
        if not self._started:
            return
        self._logger.info("JARVIS shutting down")
        self.event_bus.publish({"event_type": "SYSTEM_STOP", "component": "core"})
        self._started = False
