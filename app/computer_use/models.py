from enum import StrEnum

from pydantic import Field, StrictInt, StrictStr

from app.agent.models import Identifier, Schema


class ComputerActionKind(StrEnum):
    MOVE_POINTER = "move_pointer"
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    TYPE = "type"
    PRESS_KEY = "press_key"
    SCROLL = "scroll"


class CoordinateTarget(Schema):
    observation_id: Identifier
    image_width: StrictInt = Field(ge=1, le=3840)
    image_height: StrictInt = Field(ge=1, le=2160)
    x: StrictInt = Field(ge=0, le=3840)
    y: StrictInt = Field(ge=0, le=2160)


class ComputerAction(Schema):
    action_id: Identifier
    request_id: Identifier
    kind: ComputerActionKind
    target: CoordinateTarget | None = None
    text: StrictStr = Field(default="", max_length=4096)
    key: StrictStr = Field(default="", max_length=64)