"""Safe optional voice runtime for JARVIS."""

from __future__ import annotations

import logging
from typing import Any


class VoiceRuntime:
    """Lifecycle-managed optional voice runtime.

    The audio subsystem is deliberately isolated from the JARVIS core.
    Actual microphone/STT/TTS backends can be attached without making
    core startup depend on local audio hardware.
    """

    def __init__(self, config: Any, event_bus: Any) -> None:
        self.config = config
        self.event_bus = event_bus
        self._started = False
        self._enabled = True
        self._policy_active = False
        self._logger = logging.getLogger("jarvis.audio")

    @property
    def started(self) -> bool:
        return self._started

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_policy_active(self, active: bool) -> None:
        self._policy_active = bool(active)

    def start(self) -> None:
        if self._started:
            return

        self._started = True
        self._enabled = True

        if getattr(self.config, "startup_speech", False):
            self.speak(
                getattr(
                    self.config,
                    "startup_phrase",
                    "JARVIS is ready and listening.",
                ),
                request_id="startup",
            )

        self.event_bus.publish(
            {
                "event_type": "VOICE_STARTED",
                "component": "voice",
            }
        )

    def enable(self) -> None:
        if not self._started:
            return
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def speak(self, message: str, request_id: str | None = None) -> bool:
        """Accept a speech request without requiring an audio backend."""

        if not self._started or not self._enabled or not self._policy_active:
            return False

        self._logger.debug(
            "JARVIS voice speech requested",
            extra={"request_id": request_id, "characters": len(message)},
        )

        self.event_bus.publish(
            {
                "event_type": "VOICE_SPEAK_REQUEST",
                "component": "voice",
                "request_id": request_id,
            }
        )
        return True

    def stop(self) -> None:
        if not self._started:
            return

        self._started = False
        self._enabled = False

        self.event_bus.publish(
            {
                "event_type": "VOICE_STOPPED",
                "component": "voice",
            }
        )
