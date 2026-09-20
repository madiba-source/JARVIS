from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.multimodal.context import MultimodalContextService
from app.multimodal.documents import DocumentParser
from app.multimodal.models import ContextItem, ScreenObservation, Sensitivity
from app.vision.capture import CapturedImage


class FakeCapture:
    def __init__(self):
        self.cancelled = False

    def capture_active_window(self):
        if self.cancelled:
            raise RuntimeError("cancelled")
        return CapturedImage(b"image", 100, 80, "a" * 64)

    def cancel(self):
        self.cancelled = True

    def reset(self):
        self.cancelled = False


class FakeProvider:
    def __init__(self, confidence=0.9):
        self.confidence = confidence
        self.cancelled = False

    def analyze_image(self, data, *, width, height):
        if self.cancelled:
            raise RuntimeError("cancelled")
        return SimpleNamespace(text="untrusted screen text", confidence=self.confidence)

    def cancel(self):
        self.cancelled = True

    def reset(self):
        self.cancelled = False


class FakeVision:
    def __init__(self, confidence=0.9):
        self.capture = FakeCapture()
        self.provider = FakeProvider(confidence)

    def cancel(self):
        self.capture.cancel()
        self.provider.cancel()

    def reset(self):
        self.capture.reset()
        self.provider.reset()


def test_context_capture_is_explicit_bounded_and_resettable():
    service = MultimodalContextService(vision=FakeVision(), max_interval_seconds=60)
    observation = service.capture_screen()
    assert observation.content == "untrusted screen text"
    with pytest.raises(RuntimeError, match="rate limit"):
        service.capture_screen()
    service.disable()
    with pytest.raises(RuntimeError, match="disabled"):
        service.capture_screen()
    service.enable()
    assert service.capture_screen(analyze=False).content == ""


def test_low_confidence_stale_and_invalid_coordinates_are_rejected():
    observation = ScreenObservation(content_hash="a" * 64, width=100, height=80, confidence=0.4)
    with pytest.raises(ValueError, match="low-confidence"):
        MultimodalContextService.validate_action_observation(observation, observation_id=observation.observation_id, x=1, y=1)
    old = observation.model_copy(update={"confidence": 0.9, "observed_at": datetime.now(timezone.utc) - timedelta(hours=2)})
    with pytest.raises(ValueError, match="expired"):
        MultimodalContextService.validate_action_observation(old, observation_id=old.observation_id, x=1, y=1)
    with pytest.raises(ValueError, match="outside"):
        MultimodalContextService.validate_action_observation(observation.model_copy(update={"confidence": 0.9}), observation_id=observation.observation_id, x=100, y=1)


def test_context_items_have_provenance_lifetime_and_sensitivity():
    item = ContextItem(source="voice", content="read this", confidence=0.8, sensitivity=Sensitivity.PERSONAL)
    assert item.source == "voice"
    assert item.is_fresh()
    assert item.expires_at > item.observed_at


def test_document_parser_structures_text_json_csv_and_ocr(tmp_path: Path):
    text = tmp_path / "note.md"
    text.write_text("# Local\ncontent")
    assert DocumentParser().parse(text).metadata["parser"] == "text"
    payload = tmp_path / "data.json"
    payload.write_text('{"a": 1}')
    assert '"a": 1' in DocumentParser().parse(payload).content
    table = tmp_path / "table.csv"
    table.write_text("a,b\n1,2\n")
    assert DocumentParser().parse(table).metadata["rows"] == "2"
    image = tmp_path / "screen.png"
    image.write_bytes(b"not-a-real-image")
    assert DocumentParser(ocr=lambda raw: "ocr text").parse(image).content == "ocr text"
    with pytest.raises(ValueError, match="OCR provider"):
        DocumentParser().parse(image)


def test_document_parser_rejects_symlinks_and_unsupported(tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("safe")
    link = tmp_path / "link.txt"
    link.symlink_to(source)
    with pytest.raises(ValueError, match="regular"):
        DocumentParser().parse(link)
    binary = tmp_path / "binary.bin"
    binary.write_bytes(b"x")
    with pytest.raises(ValueError, match="unsupported"):
        DocumentParser().parse(binary)
