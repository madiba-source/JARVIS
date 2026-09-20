"""On-demand screen capture; no continuous stream and no permanent storage."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .config import VisionConfig


@dataclass(frozen=True)
class CapturedImage:
    data: bytes
    width: int
    height: int
    content_hash: str


class ScreenCaptureProvider:
    def __init__(self, config: VisionConfig | None = None) -> None:
        self.config = config or VisionConfig()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def reset(self) -> None:
        self._cancelled = False

    def capture_active_window(self) -> CapturedImage:
        if self._cancelled:
            raise RuntimeError("capture cancelled")
        try:
            from PIL import ImageGrab
            image = ImageGrab.grab()
            image.thumbnail((self.config.max_image_width, self.config.max_image_height))
            from io import BytesIO
            stream = BytesIO()
            image.save(stream, format="PNG", optimize=True)
            data = stream.getvalue()
        except Exception as error:
            raise RuntimeError(type(error).__name__) from None
        if len(data) > self.config.max_image_bytes:
            raise RuntimeError("capture exceeds image byte limit")
        return CapturedImage(data=data, width=image.width, height=image.height,
                             content_hash=hashlib.sha256(data).hexdigest())