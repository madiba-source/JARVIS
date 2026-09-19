"""Typed browser operations used only behind the Phase 04 policy registry."""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from .models import ExtractRequest, NavigateRequest, ScreenshotRequest, TargetRequest, TypeTextRequest
from .provider import BrowserProvider


class BrowserExecutor:
    def __init__(self, provider: BrowserProvider) -> None:
        self.provider = provider

    def read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.provider.ensure_started()
        operation = str(arguments.get("operation", ""))
        payload = {key: value for key, value in arguments.items() if key != "operation"}
        if operation == "navigate":
            request = NavigateRequest.model_validate(payload)
            observation = self.provider.navigate(request.url, request.timeout_ms)
        elif operation == "inspect":
            request = ExtractRequest.model_validate(payload)
            observation = self.provider.inspect()
            if request.max_chars < len(observation.visible_text):
                observation = observation.model_copy(update={"visible_text": observation.visible_text[:request.max_chars], "truncated": True})
        elif operation == "screenshot":
            request = ScreenshotRequest.model_validate(payload)
            return self.screenshot(request)
        else:
            raise ValueError("browser read operation is not supported")
        return {"code": "success", "message": "browser observation ready",
            "data": {"observation": observation.model_dump(mode="json"),
                 "trust": observation.trust.value}}

    def action(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.provider.ensure_started()
        operation = str(arguments.get("operation", ""))
        payload = {key: value for key, value in arguments.items() if key != "operation"}
        if operation == "click":
            request = TargetRequest.model_validate(payload)
            observation = self.provider.click(request.strategy, request.target, request.timeout_ms)
        elif operation == "type":
            request = TypeTextRequest.model_validate(payload)
            observation = self.provider.type_text(request.strategy, request.target, request.text, request.timeout_ms)
        else:
            raise ValueError("browser action operation is not supported")
        return {"code": "success", "message": "browser action completed",
            "data": {"observation": observation.model_dump(mode="json"),
                 "trust": observation.trust.value}}

    def screenshot(self, request: ScreenshotRequest) -> dict[str, Any]:
        page = self.provider._page_or_raise()
        self.provider._count_action()
        raw = page.screenshot(full_page=request.full_page)
        if len(raw) > request.max_bytes:
            raise ValueError("screenshot exceeds configured limit")
        return {"code": "success", "message": "browser screenshot ready", "data": {
            "observation_id": request.request_id, "content_hash": hashlib.sha256(raw).hexdigest(),
            "image_base64": base64.b64encode(raw).decode("ascii"), "bytes": len(raw),
            "trust": "UNTRUSTED_EXTERNAL_DATA"}}