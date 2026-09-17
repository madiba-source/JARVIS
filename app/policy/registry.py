"""Bootstrap registry with owned immutable policy snapshots and no public executor getter."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from .enums import AuthorizationLevel

Executor = Callable[[dict[str, Any]], dict[str, Any]]


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


class ToolDefinition(BaseModel):
    """Registration input; only accepted during bootstrap."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    tool_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str
    authorization_level: AuthorizationLevel
    requires_confirmation: bool
    supported_operations: tuple[str, ...]
    operation_models: dict[str, type[BaseModel]]
    resource_requirements: dict[str, float] = Field(default_factory=dict)
    available_offline: bool = True
    external_side_effect: bool = False
    modify_user_data: bool = False
    spawn_processes: bool = False
    access_network: bool = False
    executor: Executor


@dataclass(frozen=True)
class ImmutableToolDefinition:
    tool_id: str
    name: str
    description: str
    authorization_level: AuthorizationLevel
    requires_confirmation: bool
    supported_operations: tuple[str, ...]
    operation_models: Mapping[str, type[BaseModel]]
    resource_requirements: Mapping[str, float]
    available_offline: bool
    external_side_effect: bool
    modify_user_data: bool
    spawn_processes: bool
    access_network: bool


@dataclass(frozen=True)
class _StoredTool:
    definition: ImmutableToolDefinition
    executor: Executor


class PolicyRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, _StoredTool] = {}
        self._frozen = False
        self._lock = threading.RLock()

    @property
    def is_frozen(self) -> bool:
        with self._lock:
            return self._frozen

    def freeze(self) -> None:
        with self._lock:
            self._frozen = True

    def register_tool(self, tool: ToolDefinition) -> None:
        with self._lock:
            if self._frozen:
                raise RuntimeError("Registry is frozen")
            if tool.tool_id in self._tools:
                raise ValueError(f"Tool already registered: {tool.tool_id}")
            definition = ImmutableToolDefinition(
                tool_id=str(tool.tool_id), name=str(tool.name), description=str(tool.description),
                authorization_level=tool.authorization_level, requires_confirmation=tool.requires_confirmation,
                supported_operations=tuple(tool.supported_operations),
                operation_models=MappingProxyType(dict(tool.operation_models)),
                resource_requirements=MappingProxyType({key: float(value) for key, value in dict(tool.resource_requirements).items()}),
                available_offline=tool.available_offline, external_side_effect=tool.external_side_effect,
                modify_user_data=tool.modify_user_data, spawn_processes=tool.spawn_processes,
                access_network=tool.access_network,
            )
            self._tools[tool.tool_id] = _StoredTool(definition=definition, executor=tool.executor)

    def get_immutable_definition(self, tool_id: str) -> ImmutableToolDefinition | None:
        with self._lock:
            stored = self._tools.get(tool_id)
            return stored.definition if stored else None

    def list_tools(self) -> Mapping[str, ImmutableToolDefinition]:
        with self._lock:
            return MappingProxyType({key: value.definition for key, value in self._tools.items()})

    def tool_exists(self, tool_id: str) -> bool:
        with self._lock:
            return tool_id in self._tools

    def _invoke_for_gateway(self, tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Called only by the service execution gateway after lease validation."""
        with self._lock:
            stored = self._tools.get(tool_id)
            if stored is None:
                raise RuntimeError(f"Tool not found: {tool_id}")
            executor = stored.executor
        return executor(arguments)
