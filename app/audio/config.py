"""Configuration for the optional JARVIS voice runtime."""

from pathlib import Path

from pydantic_settings import BaseSettings


class AudioConfig(BaseSettings):
    """Voice configuration loaded from JARVIS_VOICE__* environment variables."""

    enabled: bool = False
    push_to_talk: bool = True
    startup_speech: bool = False
    startup_phrase: str = "JARVIS is ready and listening."
    stt_model: str = "tiny"
    stt_model_dir: Path = Path("./models/stt")
    tts_model: str = "voice.onnx"
    tts_model_dir: Path = Path("./models/tts")
