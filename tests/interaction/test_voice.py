import pytest

from app.agent.cancel import CancellationToken
from app.interaction.voice import SpeechController, VoiceTurnDetector


def test_voice_turn_is_bounded_by_silence():
    chunks = iter([("hello", True), ("there", True), ("", False), ("", False)])
    detector = VoiceTurnDetector(max_seconds=1, silence_seconds=0.0001)
    assert detector.capture(lambda: next(chunks)) == "hello there"


def test_voice_turn_cancellation_propagates():
    token = CancellationToken()
    token.cancel("barge-in")
    with pytest.raises(Exception, match="barge-in"):
        VoiceTurnDetector(max_seconds=1).capture(lambda: ("", True), token=token)


def test_speech_controller_interrupts_previous_speech():
    tokens = []
    controller = SpeechController(lambda _text, token: tokens.append(token))
    first = controller.speak("first")
    second = controller.speak("second")
    assert first.is_cancelled
    assert not second.is_cancelled
    controller.stop()
    assert second.is_cancelled
