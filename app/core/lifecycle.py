"""Minimal, explicit JARVIS lifecycle for foundation validation."""

import logging
from typing import Any

from .config import Settings
from .events import EventBus


class JarvisCore:
    """Owns only startup and shutdown state during Phase 01."""

    def __init__(self, settings: Settings | None = None, event_bus: EventBus | None = None,
                 *, agent_config: Any = None, agent_router: Any = None,
                 policy_service: Any = None) -> None:
        self.settings = settings or Settings()
        self.event_bus = event_bus or EventBus()
        self._agent_config = agent_config
        self._agent_router = agent_router
        self._policy_service = policy_service
        self._runtime_policy_service = None
        self._started = False
        self.agent_runtime = None
        self.agent_runtime_error: str | None = None
        self.hud_runtime = None
        self.memory_runtime = None
        self.voice_runtime = None
        self.calendar_runtime = None
        self.proactive_runtime = None
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
        if self.settings.memory_enabled or self.settings.calendar.enabled or self.settings.automation_enabled:
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
        self._start_proactive_runtime()
        self._start_agent_runtime()
        self._start_hud()
        self._started = True
        self._logger.info("JARVIS ready")
        self.event_bus.publish({"event_type": "SYSTEM_READY", "component": "core"})
        self._start_voice()

    def disable(self) -> None:
        """Stop JARVIS-managed work while leaving the desktop untouched."""
        if self.agent_runtime is not None:
            self.agent_runtime.disable()
        if self._runtime_policy_service is not None:
            try:
                self._runtime_policy_service.set_jarvis_active(False)
            except Exception:
                self._logger.exception("JARVIS policy disable failed")
        if self.voice_runtime is not None:
            self.voice_runtime.disable()
        if self.hud_runtime is not None:
            self.hud_runtime.disable()
        if self.calendar_runtime is not None and self.calendar_runtime.scheduler is not None:
            self.calendar_runtime.scheduler.stop()
        if self.proactive_runtime is not None:
            self.proactive_runtime.disable()

    def enable(self) -> None:
        """Resume JARVIS-managed services without creating duplicate runtimes."""
        if self._runtime_policy_service is not None:
            self._runtime_policy_service.set_jarvis_active(True)
        if self.agent_runtime is not None:
            self.agent_runtime.enable()
        if self.voice_runtime is not None:
            self.voice_runtime.enable()
        if self.calendar_runtime is not None and self.calendar_runtime.scheduler is not None:
            self.calendar_runtime.scheduler.start()
        if self.proactive_runtime is not None:
            self.proactive_runtime.enable()
        if self.hud_runtime is not None:
            self.hud_runtime.enable()

    def _start_hud(self) -> None:
        if not self.settings.hud_enabled:
            return
        try:
            from app.hud import HudRuntime
            self.hud_runtime = HudRuntime()
            if not self.hud_runtime.start():
                self._logger.warning("JARVIS HUD unavailable", extra={"error": self.hud_runtime.error})
        except Exception as error:
            self.hud_runtime = None
            self._logger.warning("JARVIS HUD startup failed", extra={"error": type(error).__name__})

    def _start_agent_runtime(self) -> None:
        router = self._agent_router
        try:
            from app.agent.config import AgentConfig
            from app.agent.coordinator import AgentRuntime
            from app.agent.providers import OllamaProvider
            from app.agent.router import ModelRouter
            from app.execution.policy import Phase04PolicyService

            config = self._agent_config or AgentConfig()
            if router is None:
                local = OllamaProvider(self.settings.ollama_host, self.settings.agent_model)
                router = ModelRouter(config, local=local)
            service = self._policy_service or Phase04PolicyService(self.settings.data_dir)
            self._runtime_policy_service = service
            self.agent_runtime = AgentRuntime(service, config=config, router=router)
            self.agent_runtime_error = None
        except Exception as error:
            self.agent_runtime = None
            self._runtime_policy_service = None
            self.agent_runtime_error = type(error).__name__[:128] or "agent runtime unavailable"
            close = getattr(router, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
            self._logger.exception("JARVIS agent runtime startup failed")

    def _build_shared_database(self) -> None:
        from app.calendar.migration import CALENDAR_MIGRATIONS
        from app.database.config import DatabaseConfig
        from app.database.service import DatabaseService
        from app.memory.migration import MEMORY_MIGRATIONS
        from app.proactive.migration import PROACTIVE_MIGRATIONS
        if self._database is None:
            self._database = DatabaseService(
                DatabaseConfig(db_path=str(self.settings.data_dir / "jarvis.db"),
                               backup_directory=str(self.settings.data_dir / "backups")),
                extension_migrations=MEMORY_MIGRATIONS + CALENDAR_MIGRATIONS + PROACTIVE_MIGRATIONS,
            )

    def _start_proactive_runtime(self) -> None:
        if not self.settings.automation_enabled or self._database is None:
            return
        try:
            from app.proactive.engine import ProactiveScheduler
            self._database.initialize()
            self.proactive_runtime = ProactiveScheduler(
                self._database, poll_seconds=self.settings.automation_poll_seconds,
                notifier=lambda message: self.event_bus.publish({"event_type": "PROACTIVE_NOTIFICATION", "message": message}),
                event_bus=self.event_bus,
            )
            self.proactive_runtime.start()
        except Exception:
            self.proactive_runtime = None
            self._logger.exception("JARVIS proactive runtime startup failed")

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
        try:
            from app.audio.runtime import VoiceRuntime
            self.voice_runtime = VoiceRuntime(self.settings.voice, self.event_bus)
            self.voice_runtime.set_policy_active(True)
            self.voice_runtime.start()
        except Exception:
            self.voice_runtime = None
            self._logger.exception("JARVIS voice startup failed")

    def shutdown(self) -> None:
        if not self._started and self.agent_runtime is None and self.memory_runtime is None \
                and self.calendar_runtime is None and self._database is None:
            return
        self._logger.info("JARVIS shutting down")
        self.event_bus.publish({"event_type": "SYSTEM_STOP", "component": "core"})
        if self.agent_runtime is not None:
            try:
                self.agent_runtime.close()
            except Exception:
                self._logger.exception("JARVIS agent runtime shutdown failed")
            self.agent_runtime = None
        if self.hud_runtime is not None:
            try:
                self.hud_runtime.close()
            except Exception:
                self._logger.exception("JARVIS HUD shutdown failed")
            self.hud_runtime = None
        if self._runtime_policy_service is not None:
            try:
                close = getattr(self._runtime_policy_service, "close", None)
                if callable(close):
                    close()
            except Exception:
                self._logger.exception("JARVIS policy service shutdown failed")
            self._runtime_policy_service = None
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
        if self.proactive_runtime is not None:
            try:
                self.proactive_runtime.stop()
            except Exception:
                self._logger.exception("JARVIS proactive runtime shutdown failed")
            self.proactive_runtime = None
        self._database = None
        self._started = False
