import pytest

from app.vision.config import VisionConfig
from app.vision.provider import UnavailableVisionProvider, VisionProvider


def test_unavailable_vision_is_explicit_and_does_not_download_models() -> None:
    provider = UnavailableVisionProvider()

    assert provider.health()["available"] is False
    with pytest.raises(RuntimeError, match="unavailable"):
        provider.analyze_image(b"x", width=1, height=1)


def test_vision_rejects_oversized_images_before_provider_call() -> None:
    provider = VisionProvider(VisionConfig(max_image_bytes=1024), client=object())

    with pytest.raises(ValueError):
        provider.analyze_image(b"x" * 1025, width=1, height=1)