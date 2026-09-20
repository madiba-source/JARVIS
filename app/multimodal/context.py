"""Explicit multimodal context assembly and on-demand screen coordination."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from app.vision.capture import ScreenCaptureProvider
from app.vision.provider import VisionProvider
from app.vision.service import VisionService

from .models import ContextItem, ScreenObservation, Sensitivity


class MultimodalContext:
    """A bounded, ephemeral context envelope; nothing is persisted implicitly."""

    def __init__(self, *, request: ContextItem | None = None,
                 screen: ScreenObservation | None = None,
                 voice: ContextItem | None = None,
                 document: ContextItem | None = None,
                 memory: ContextItem | None = None,
                 workflow: ContextItem | None = None,
                 tool_state: ContextItem | None = None) -> None:
        self.request = request
        self.screen = screen
        self.voice = voice
        self.document = document
        self.memory = memory
        self.workflow = workflow
        self.tool_state = tool_state

    def items(self) -> tuple[ContextItem, ...]:
        return tuple(item for item in (self.request, self.screen, self.voice, self.document, self.memory, self.workflow, self.tool_state) if item is not None)

    def model_dump(self) -> dict[str, Any]:
        return {name: item.model_dump(mode="json") for name, item in (("request", self.request), ("screen", self.screen), ("voice", self.voice), ("document", self.document), ("memory", self.memory), ("workflow", self.workflow), ("tool_state", self.tool_state)) if item is not None}


class MultimodalContextService:
    """Explicit local-only capture/context service with a global kill switch."""

    def __init__(self, *, vision: VisionService | None = None, max_interval_seconds: float = 1.0) -> None:
        self.vision = vision or VisionService(ScreenCaptureProvider(), VisionProvider())
        self.max_interval_seconds = max(0.1, min(max_interval_seconds, 60.0))
        self._enabled = True
        self._last_capture = 0.0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def disable(self) -> None:
        self._enabled = False
        self.vision.cancel()

    def enable(self) -> None:
        self._enabled = True
        self._last_capture = 0.0
        reset = getattr(self.vision, "reset", None)
        if callable(reset):
            reset()

    def capture_screen(self, *, analyze: bool = True, sensitivity: Sensitivity = Sensitivity.UNKNOWN) -> ScreenObservation:
        if not self._enabled:
            raise RuntimeError("multimodal capture disabled")
        now = time.monotonic()
        if now - self._last_capture < self.max_interval_seconds:
            raise RuntimeError("screen capture rate limit")
        self._last_capture = now
        image = self.vision.capture.capture_active_window()
        text = ""
        confidence = None
        if analyze:
            observation = self.vision.provider.analyze_image(image.data, width=image.width, height=image.height)
            text = observation.text
            confidence = observation.confidence
        return ScreenObservation(content_hash=image.content_hash, width=image.width, height=image.height, content=text, confidence=confidence, sensitivity=sensitivity)

    @staticmethod
    def validate_action_observation(observation: ScreenObservation, *, observation_id: str, x: int, y: int, now: datetime | None = None) -> None:
        if observation.observation_id != observation_id:
            raise ValueError("stale screen observation")
        if not observation.is_fresh(now):
            raise ValueError("expired screen observation")
        if x < 0 or y < 0 or x >= observation.width or y >= observation.height:
            raise ValueError("screen coordinate outside observation")
        if observation.confidence is not None and observation.confidence < 0.7:
            raise ValueError("low-confidence screen observation requires confirmation")

    def assemble(self, **items: ContextItem | None) -> MultimodalContext:
        if not self._enabled:
            raise RuntimeError("multimodal context disabled")
        return MultimodalContext(**{key: value for key, value in items.items() if key in {"request", "screen", "voice", "document", "memory", "workflow", "tool_state"}})
