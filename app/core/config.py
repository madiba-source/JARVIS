"""Phase 01 configuration loaded from environment variables and .env."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    ollama_host: str = "http://127.0.0.1:11434"
    log_level: str = "INFO"
    data_dir: Path = Path("./data")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="JARVIS_",
        extra="ignore",
    )
