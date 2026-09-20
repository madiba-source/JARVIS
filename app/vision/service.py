"""Bounded observe/analyze orchestration without persistent screenshots."""

from __future__ import annotations

from .capture import ScreenCaptureProvider
from .provider import VisionProvider


class VisionService:
    def __init__(self, capture: ScreenCaptureProvider, provider: VisionProvider) -> None:
        self.capture = capture
        self.provider = provider

    def describe_screen(self):
        image = self.capture.capture_active_window()
        return self.provider.analyze_image(image.data, width=image.width, height=image.height)

    def cancel(self) -> None:
        self.capture.cancel()
        self.provider.cancel()

    def reset(self) -> None:
        for component in (self.capture, self.provider):
            reset = getattr(component, "reset", None)
            if callable(reset):
                reset()