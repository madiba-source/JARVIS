"""Bounded observability configuration."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ObservabilityConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    log_level: str = "INFO"
    log_directory: Path | None = Path("logs")
    max_log_size_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    backup_count: int = Field(default=5, ge=0, le=100)
    sqlite_path: Path | None = Path("data/observability.db")
    max_sqlite_rows: int = Field(default=50_000, ge=1)
    sqlite_max_bytes: int = Field(default=50 * 1024 * 1024, ge=1 * 1024 * 1024)
    sqlite_retention_days: int | None = Field(default=30, ge=1)
    console_logging: bool = True
    metrics_enabled: bool = True
    tracing_enabled: bool = True
    opentelemetry_enabled: bool = False
    max_metric_series: int = Field(default=256, ge=1)
    max_metric_labels: int = Field(default=4, ge=1)
    max_event_payload_bytes: int = Field(default=64 * 1024, ge=1024)
    max_metadata_depth: int = Field(default=8, ge=1, le=32)
    max_trace_count: int = Field(default=256, ge=1)
    max_spans_per_trace: int = Field(default=64, ge=1)
    max_span_attributes: int = Field(default=32, ge=1)
    max_span_events: int = Field(default=32, ge=1)
    max_attribute_value_bytes: int = Field(default=2048, ge=64)
    max_event_queue: int = Field(default=1024, ge=1)
