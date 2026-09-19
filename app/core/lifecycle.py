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
        self.memory_runtime = None
        self.voice_runtime = None
        self.calendar_runtime = None
        self._database = None
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
        if self.settings.memory_enabled or self.settings.calendar.enabled:
            self._build_shared_database()
        if self.settings.memory_enabled:
            from app.memory.runtime import MemoryRuntime
            self.memory_runtime = MemoryRuntime(
                self.settings.data_dir, self.settings.memory, self.event_bus,
                vector_enabled=self.settings.memory_vector_enabled,
                database=self._database,
            )
            self._logger.info("JARVIS memory status", extra={"available": self.memory_runtime.available})
        if self.settings.calendar.enabled:
            from app.calendar.runtime import CalendarRuntime
            self.calendar_runtime = CalendarRuntime(
                self.settings.data_dir, self.settings.calendar, self.event_bus,
                database=self._database, announce=self._voice_announce,
            )
            self._logger.info("JARVIS calendar status", extra={"available": self.calendar_runtime.available})
        self._started = True
        self._logger.info("JARVIS ready")
        self.event_bus.publish({"event_type": "SYSTEM_READY", "component": "core"})
        self._start_voice()

    def _build_shared_database(self) -> None:
        from app.calendar.migration import CALENDAR_MIGRATIONS
        from app.database.config import DatabaseConfig
        from app.database.service import DatabaseService
        from app.memory.migration import MEMORY_MIGRATIONS
        if self._database is None:
            self._database = DatabaseService(
                DatabaseConfig(db_path=str(self.settings.data_dir / "jarvis.db"),
                               backup_directory=str(self.settings.data_dir / "backups")),
                extension_migrations=MEMORY_MIGRATIONS + CALENDAR_MIGRATIONS,
            )

    def _voice_announce(self, message: str) -> None:
        voice = self.voice_runtime
        if voice is not None and getattr(voice, "_started", False):
            try:
                voice.speak(message, request_id="calendar")
            except Exception:
                self._logger.exception("JARVIS calendar announce failed")

    def _start_voice(self) -> None:
        if not self.settings.voice.enabled:
            return
        from app.audio.runtime import VoiceRuntime
        self.voice_runtime = VoiceRuntime(self.settings.voice, self.event_bus)
        try:
            self.voice_runtime.set_policy_active(True)
            self.voice_runtime.start()
        except Exception:
            self._logger.exception("JARVIS voice startup failed")
            self.voice_runtime = None

    def shutdown(self) -> None:
        if not self._started:
            return
        self._logger.info("JARVIS shutting down")
        self.event_bus.publish({"event_type": "SYSTEM_STOP", "component": "core"})
        if self.voice_runtime is not None:
            try:
                self.voice_runtime.stop()
            except Exception:
                self._logger.exception("JARVIS voice shutdown failed")
            self.voice_runtime = None
        if self.memory_runtime is not None:
            self.memory_runtime.close()
            self.memory_runtime = None
        if self.calendar_runtime is not None:
            try:
                self.calendar_runtime.close()
            except Exception:
                self._logger.exception("JARVIS calendar shutdown failed")
            self.calendar_runtime = None
        self._database = None
        self._started = False
