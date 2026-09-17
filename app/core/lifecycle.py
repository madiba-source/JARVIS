"""Minimal, explicit JARVIS lifecycle for foundation validation."""

import logging

from .config import Settings


class JarvisCore:
    """Owns only startup and shutdown state during Phase 01."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._started = False
        self._logger = logging.getLogger("jarvis.core")

    @property
    def is_running(self) -> bool:
        return self._started

    def start(self) -> None:
        if self._started:
            return
        self._logger.info("JARVIS starting", extra={"environment": self.settings.environment})
        self._logger.info("JARVIS environment", extra={"ollama_host": self.settings.ollama_host})
        self._started = True
        self._logger.info("JARVIS ready")

    def shutdown(self) -> None:
        if not self._started:
            return
        self._logger.info("JARVIS shutting down")
        self._started = False
