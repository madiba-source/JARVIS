from pydantic import Field, StrictBool

from app.agent.models import Schema


class VisionConfig(Schema):
    enabled: StrictBool = True
    model: str = Field(default="llava:7b", min_length=1, max_length=128)
    max_image_width: int = Field(default=1920, strict=True, ge=1, le=3840)
    max_image_height: int = Field(default=1080, strict=True, ge=1, le=2160)
    max_image_bytes: int = Field(default=4_194_304, strict=True, ge=1024, le=16_777_216)
    inference_timeout_seconds: float = Field(default=60, strict=True, gt=0, le=180)
    max_observations: int = Field(default=8, strict=True, ge=1, le=32)