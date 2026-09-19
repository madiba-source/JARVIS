"""Read-only view of the trusted tool registry.

The runtime, the planner and the model may see *definitions*: stable tool ids,
their supported operations, their authorization level and whether they need
confirmation. They never see executors. Executors stay behind the Phase 03/04
gateway, which is the only code allowed to invoke them.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel

from app.policy.enums import AuthorizationLevel
from app.policy.snapshot import OwnedArgumentsSnapshot

from .errors import ArgumentRejected, UnknownOperation, UnknownTool

MAX_DESCRIBED_TOOLS = 32
MAX_DESCRIBED_OPERATIONS = 16


@dataclass(frozen=True)
class ToolView:
    """One registered tool, described without any executable reference."""

    tool_id: str
    operations: tuple[str, ...]
    authorization_level: AuthorizationLevel
    requires_confirmation: bool
    external_side_effect: bool
    modify_user_data: bool
    spawn_processes: bool
    access_network: bool
    available_offline: bool

    @property
    def side_effecting(self) -> bool:
        return self.external_side_effect or self.modify_user_data or self.spawn_processes


class ToolCatalog:
    """Immutable snapshot of registry definitions plus their argument models."""

    def __init__(self, registry: Any) -> None:
        views: dict[str, ToolView] = {}
        models: dict[tuple[str, str], type[BaseModel]] = {}
        for tool_id, definition in dict(registry.list_tools()).items():
            views[str(tool_id)] = ToolView(
                tool_id=str(tool_id),
                operations=tuple(str(op) for op in definition.supported_operations),
                authorization_level=definition.authorization_level,
                requires_confirmation=bool(definition.requires_confirmation),
                external_side_effect=bool(definition.external_side_effect),
                modify_user_data=bool(definition.modify_user_data),
                spawn_processes=bool(definition.spawn_processes),
                access_network=bool(definition.access_network),
                available_offline=bool(definition.available_offline),
            )
            for operation, model in dict(definition.operation_models).items():
                models[(str(tool_id), str(operation))] = model
        self._views = MappingProxyType(views)
        self._models = MappingProxyType(models)

    # --- reads ----------------------------------------------------------
    @property
    def tool_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._views))

    def view(self, tool_id: str) -> ToolView | None:
        return self._views.get(tool_id)

    def require_view(self, tool_id: str) -> ToolView:
        view = self._views.get(tool_id)
        if view is None:
            raise UnknownTool("tool is not registered")
        return view

    def has_operation(self, tool_id: str, operation: str) -> bool:
        return (tool_id, operation) in self._models

    def operations(self, tool_id: str) -> tuple[str, ...]:
        view = self._views.get(tool_id)
        return view.operations if view else ()

    def requires_confirmation(self, tool_id: str) -> bool:
        view = self._views.get(tool_id)
        return bool(view and view.requires_confirmation)

    def is_side_effecting(self, tool_id: str) -> bool:
        view = self._views.get(tool_id)
        return bool(view and view.side_effecting)

    def authorization_level(self, tool_id: str) -> AuthorizationLevel | None:
        view = self._views.get(tool_id)
        return view.authorization_level if view else None

    # --- validation -----------------------------------------------------
    def validate_arguments(self, tool_id: str, operation: str, arguments: object) -> dict[str, Any]:
        """Validate arguments against the trusted operation model.

        This is a pre-flight rejection only. The authoritative validation still
        happens inside policy evaluation; this exists so a malformed plan never
        reaches an execution attempt.
        """
        model = self._models.get((tool_id, operation))
        if model is None:
            if tool_id not in self._views:
                raise UnknownTool("tool is not registered")
            raise UnknownOperation("operation is not registered")
        try:
            validated = model.model_validate(arguments)
            snapshot = OwnedArgumentsSnapshot.capture(validated.model_dump(mode="python"))
            return snapshot.materialize()
        except (ValueError, TypeError, RecursionError, AttributeError):
            raise ArgumentRejected("argument validation failed") from None

    # --- model-visible description --------------------------------------
    def describe(self) -> tuple[dict[str, Any], ...]:
        """A bounded, executor-free description for structured model prompts."""
        described: list[dict[str, Any]] = []
        for tool_id in sorted(self._views)[:MAX_DESCRIBED_TOOLS]:
            view = self._views[tool_id]
            described.append({
                "tool_id": view.tool_id,
                "operations": list(view.operations[:MAX_DESCRIBED_OPERATIONS]),
                "authorization_level": int(view.authorization_level),
                "requires_confirmation": view.requires_confirmation,
                "side_effecting": view.side_effecting,
            })
        return tuple(described)
