"""Argument ownership contracts using only in-memory fake executors."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import FrozenInstanceError
from threading import Event
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, field_validator

from app.policy import AuthorizationLevel, DecisionState, PolicyEngineService, ToolRequest
from app.policy.evaluator import ExecutionPermit
from app.policy.registry import ToolDefinition
from app.policy.snapshot import OwnedArgumentsSnapshot


class NestedArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: dict[str, Any]
    sequence: tuple[int, ...]


def make_service(schema: type[BaseModel] = NestedArgs) -> PolicyEngineService:
    class TestService(PolicyEngineService):
        def _register_defaults(self) -> None:
            self.registry.register_tool(ToolDefinition(
                tool_id="owned_test",
                name="Owned test",
                description="In-memory argument echo",
                authorization_level=AuthorizationLevel.L0_READ_ONLY,
                requires_confirmation=False,
                supported_operations=("inspect",),
                operation_models={"inspect": schema},
                executor=lambda arguments: arguments,
            ))
            self.registry.freeze()

    return TestService()


def make_request() -> ToolRequest:
    return ToolRequest(
        request_id="owned-request",
        tool_name="owned_test",
        operation="inspect",
        authorization_level=AuthorizationLevel.L0_READ_ONLY,
        arguments={
            "payload": {
                "nested": {"name": "original"},
                "items": [{"deep": {"values": [1, 2, 3]}}],
            },
            "sequence": (4, 5),
        },
        originating_subsystem="test",
    )


def mutate(request: ToolRequest) -> None:
    request.arguments["payload"]["nested"]["name"] = "changed"
    request.arguments["payload"]["items"][0]["deep"]["values"].append(99)
    request.arguments["payload"]["items"].append({"extra": True})
    request.arguments["sequence"] = (99,)
    request.arguments["extra"] = "not authorized"


def authorize(service: PolicyEngineService, request: ToolRequest) -> ExecutionPermit:
    decision, permit = service.process_request(request)
    assert decision.decision is DecisionState.ALLOW
    assert permit is not None
    return permit


def test_post_authorization_nested_mutation_executes_original_snapshot() -> None:
    service = make_service()
    request = make_request()
    expected = deepcopy(request.arguments)
    permit = authorize(service, request)
    mutate(request)
    assert service.execute_with_permit(request, permit) == expected


def test_gateway_does_not_read_arguments_even_if_replaced() -> None:
    service = make_service()
    request = make_request()
    expected = deepcopy(request.arguments)
    permit = authorize(service, request)
    request.arguments.clear()
    assert service.execute_with_permit(request, permit) == expected


def test_snapshot_round_trip_preserves_mapping_list_and_tuple_types() -> None:
    service = make_service()
    request = make_request()
    expected = deepcopy(request.arguments)
    permit = authorize(service, request)
    restored = ExecutionPermit.model_validate_json(permit.model_dump_json())
    mutate(request)
    result = service.execute_with_permit(request, restored)
    assert result == expected
    assert type(result) is dict
    assert type(result["payload"]["items"]) is list
    assert type(result["sequence"]) is tuple


def test_executor_payload_mutation_does_not_change_authorized_snapshot() -> None:
    service = make_service()
    request = make_request()
    expected = deepcopy(request.arguments)
    permit = authorize(service, request)
    result = service.execute_with_permit(request, permit)
    result["payload"]["items"][0]["deep"]["values"].clear()
    assert service.execute_with_permit(request, permit) == expected


def test_snapshot_is_immutable_and_materializations_are_independent() -> None:
    original = make_request().arguments
    expected = deepcopy(original)
    snapshot = OwnedArgumentsSnapshot.capture(original)
    with pytest.raises(FrozenInstanceError):
        snapshot.payload = ""
    original["payload"]["nested"].clear()
    first = snapshot.materialize()
    first["payload"]["items"].clear()
    assert snapshot.materialize() == expected


def test_schema_normalization_is_not_repeated_during_execution() -> None:
    calls = []

    class NormalizedArgs(NestedArgs):
        @field_validator("sequence")
        @classmethod
        def normalize(cls, value: tuple[int, ...]) -> tuple[int, ...]:
            calls.append(1)
            return value + (6,)

    service = make_service(NormalizedArgs)
    request = make_request()
    expected = deepcopy(request.arguments)
    expected["sequence"] = (4, 5, 6)
    permit = authorize(service, request)
    assert service.execute_with_permit(request, permit) == expected
    assert calls == [1]


def test_synchronized_mutation_during_validation_cannot_change_owned_input() -> None:
    validation_started = Event()
    continue_validation = Event()

    class PausedArgs(NestedArgs):
        @field_validator("payload", mode="before")
        @classmethod
        def pause(cls, value: Any) -> Any:
            validation_started.set()
            if not continue_validation.wait(timeout=5):
                raise ValueError("test synchronization timed out")
            return value

    service = make_service(PausedArgs)
    request = make_request()
    expected = deepcopy(request.arguments)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.process_request, request)
        try:
            assert validation_started.wait(timeout=5)
            mutate(request)
        finally:
            continue_validation.set()
        decision, permit = future.result(timeout=5)
    assert decision.decision is DecisionState.ALLOW
    assert permit is not None
    assert service.execute_with_permit(request, permit) == expected


def test_synchronized_mutation_after_lease_admission_uses_snapshot(monkeypatch) -> None:
    admitted = Event()
    continue_dispatch = Event()
    service = make_service()
    request = make_request()
    expected = deepcopy(request.arguments)
    permit = authorize(service, request)
    original_acquire = service.evaluator.acquire_execution_lease

    def paused_acquire(candidate, caller):
        lease = original_acquire(candidate, caller)
        admitted.set()
        if not continue_dispatch.wait(timeout=5):
            lease.__exit__(None, None, None)
            raise RuntimeError("test synchronization timed out")
        return lease

    monkeypatch.setattr(service.evaluator, "acquire_execution_lease", paused_acquire)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.execute_with_permit, request, permit)
        try:
            assert admitted.wait(timeout=5)
            mutate(request)
        finally:
            continue_dispatch.set()
        assert future.result(timeout=5) == expected


def test_lease_owns_permit_budget_and_rejects_payload_access_after_release() -> None:
    service = make_service()
    request = make_request()
    permit = authorize(service, request)
    with service.evaluator.acquire_execution_lease(permit, request) as lease:
        permit.effective_budget["memory_mb"] = 999
        assert lease.permit.effective_budget == {}
        assert lease.execution_arguments() == request.arguments
    with pytest.raises(PermissionError, match="released"):
        lease.execution_arguments()


@pytest.mark.parametrize("unsupported", [{1, 2}, frozenset({1}), float("nan")])
def test_noncanonical_values_never_receive_permits(unsupported) -> None:
    service = make_service()
    request = make_request()
    request.arguments["payload"]["unsupported"] = unsupported
    decision, permit = service.process_request(request)
    assert decision.decision is DecisionState.INVALID_REQUEST
    assert permit is None