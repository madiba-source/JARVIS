"""How the runtime obtains a confirmation token.

Confirmation is a human decision. The runtime never invents one, never caches
one, and never reuses one: tokens are single-use, action-bound and expire.

The default provider refuses. A deny is escalated to the human, and the step
becomes `awaiting_confirmation` rather than executing without approval.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.policy.models import ToolRequest

from .plan_validation import ValidatedStep


@runtime_checkable
class ConfirmationProvider(Protocol):
    """Resolves a pending confirmation into a token, or refuses."""

    def resolve(self, step: ValidatedStep, request: ToolRequest) -> str | None:
        """Return a token for exactly this request, or None to escalate."""


class DenyConfirmationProvider:
    """Fails closed. Used unless an interface supplies a real decision."""

    def resolve(self, step: ValidatedStep, request: ToolRequest) -> str | None:
        return None

    def describe(self) -> dict[str, Any]:
        return {"provider": "deny"}


class AutoConfirmProvider:
    """Issues a real confirmation token through the gateway.

    This does not bypass confirmation; it asks the *existing* confirmation
    manager to mint the same action-bound token an operator would approve, using
    the same request identity. It exists for supervised sessions and tests.
    """

    def __init__(self, gateway: Any, *, max_tokens: int = 16) -> None:
        self._gateway = gateway
        self._max_tokens = max(1, int(max_tokens))
        self._issued = 0

    def resolve(self, step: ValidatedStep, request: ToolRequest) -> str | None:
        if self._issued >= self._max_tokens:
            return None
        try:
            token = self._gateway.issue_confirmation(request)
        except Exception:
            return None
        if not isinstance(token, str) or not token.strip():
            return None
        self._issued += 1
        return token

    def describe(self) -> dict[str, Any]:
        return {"provider": "auto", "issued": self._issued}


class ScriptedConfirmationProvider:
    """Deterministic provider for tests: a fixed token or a refusal."""

    def __init__(self, token: str | None = None) -> None:
        self._token = token
        self.requests: list[str] = []

    def resolve(self, step: ValidatedStep, request: ToolRequest) -> str | None:
        self.requests.append(request.request_id)
        return self._token

    def describe(self) -> dict[str, Any]:
        return {"provider": "scripted", "requests": len(self.requests)}
