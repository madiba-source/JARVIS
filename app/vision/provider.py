"""Typed local vision provider; unavailable is a normal offline state."""

from __future__ import annotations

import base64
import threading
from typing import Any

from .config import VisionConfig
from .models import VisionObservation


class VisionProvider:
    def __init__(self, config: VisionConfig | None = None, client: Any = None) -> None:
        self.config = config or VisionConfig()
        self._client = client
        self._cancelled = False
        self._lock = threading.Lock()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True

    def reset(self) -> None:
        with self._lock:
            self._cancelled = False

    def health(self) -> dict[str, Any]:
        return {"available": self._client is not None and self.config.enabled,
                "model": self.config.model}

    def analyze_image(self, image: bytes, *, width: int, height: int) -> VisionObservation:
        if not self.config.enabled:
            raise RuntimeError("vision disabled")
        if len(image) > self.config.max_image_bytes or width > self.config.max_image_width or height > self.config.max_image_height:
            raise ValueError("image exceeds vision limits")
        with self._lock:
            if self._cancelled:
                raise RuntimeError("vision cancelled")
        if self._client is None:
            raise RuntimeError("vision provider unavailable")
        response = self._client.generate(model=self.config.model, prompt="Describe the image as bounded JSON data.", images=[base64.b64encode(image).decode("ascii")], options={"temperature": 0.0})
        text = response.get("response", "") if isinstance(response, dict) else getattr(response, "response", "")
        if not isinstance(text, str):
            raise RuntimeError("malformed vision response")
        return VisionObservation(image_width=width, image_height=height, text=text[:16_384])


class UnavailableVisionProvider(VisionProvider):
    def __init__(self, config: VisionConfig | None = None) -> None:
        super().__init__(config=config, client=None)