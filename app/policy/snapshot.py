"""Immutable execution payload encoding for canonical policy arguments.

The wire representation preserves list/tuple distinctions without pickle or
execution-time schema reinterpretation. Only canonical policy values qualify.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .confirmation import _canonical


def _encode(value: Any) -> Any:
    if isinstance(value, Mapping):
        return ["mapping", [[key, _encode(item)] for key, item in value.items()]]
    if isinstance(value, list):
        return ["list", [_encode(item) for item in value]]
    if isinstance(value, tuple):
        return ["tuple", [_encode(item) for item in value]]
    return ["scalar", value]


def _decode(node: Any) -> Any:
    if not isinstance(node, list) or len(node) != 2:
        raise ValueError("invalid snapshot node")
    kind, value = node
    if kind == "scalar":
        if value is not None and type(value) not in (bool, int, float, str):
            raise ValueError("invalid snapshot scalar")
        return value
    if not isinstance(value, list):
        raise ValueError("invalid snapshot collection")
    if kind == "mapping":
        result = {}
        for pair in value:
            if not isinstance(pair, list) or len(pair) != 2:
                raise ValueError("invalid snapshot mapping entry")
            key, item = pair
            if not isinstance(key, str) or key in result:
                raise ValueError("invalid snapshot mapping key")
            result[key] = _decode(item)
        return result
    if kind == "list":
        return [_decode(item) for item in value]
    if kind == "tuple":
        return tuple(_decode(item) for item in value)
    raise ValueError("invalid snapshot kind")


@dataclass(frozen=True)
class OwnedArgumentsSnapshot:
    """An immutable string; each materialization produces an independent payload."""

    payload: str

    @classmethod
    def capture(cls, arguments: dict[str, Any]) -> OwnedArgumentsSnapshot:
        # Preserve the existing admissible value domain, including finite floats.
        _canonical(arguments)
        payload = json.dumps(_encode(arguments), separators=(",", ":"), allow_nan=False)
        return cls(payload)

    def materialize(self) -> dict[str, Any]:
        arguments = _decode(json.loads(self.payload))
        if not isinstance(arguments, dict):
            raise ValueError("snapshot arguments must be a mapping")
        _canonical(arguments)
        return arguments