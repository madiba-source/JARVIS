import pytest

from app.computer_use.controller import ComputerUseController, EmergencyStop
from app.computer_use.models import ComputerAction, ComputerActionKind, CoordinateTarget


def _action(observation_id: str, x: int = 10, y: int = 10) -> ComputerAction:
    return ComputerAction(
        action_id="action-1", request_id="request-1", kind=ComputerActionKind.CLICK,
        target=CoordinateTarget(observation_id=observation_id, image_width=100, image_height=100, x=x, y=y),
    )


def test_stale_coordinate_observation_is_rejected() -> None:
    controller = ComputerUseController(executor=object())

    with pytest.raises(ValueError, match="stale"):
        controller.execute(_action("old"), current_observation_id="new")


def test_out_of_bounds_coordinate_is_rejected() -> None:
    controller = ComputerUseController(executor=object())

    with pytest.raises(ValueError, match="outside"):
        controller.execute(_action("current", x=100), current_observation_id="current")


def test_emergency_stop_is_idempotent_and_blocks_new_actions() -> None:
    controller = ComputerUseController(executor=object())
    controller.stop()
    controller.stop()

    with pytest.raises(EmergencyStop):
        controller.execute(_action("current"), current_observation_id="current")