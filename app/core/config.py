"""Phase 01 configuration loaded from environment variables and .env."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.audio.config import AudioConfig
from app.calendar.config import CalendarConfig
from app.memory.config import MemoryConfig


class Settings(BaseSettings):
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    ollama_host: str = "http://127.0.0.1:11434"
    agent_model: str = "llama3.2"
    log_level: str = "INFO"
    data_dir: Path = Path("./data")
    memory_enabled: bool = True
    memory_vector_enabled: bool = False
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    voice: AudioConfig = Field(default_factory=AudioConfig)
    calendar: CalendarConfig = Field(default_factory=CalendarConfig)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="JARVIS_",
        env_nested_delimiter="__",
        extra="ignore",
    )
