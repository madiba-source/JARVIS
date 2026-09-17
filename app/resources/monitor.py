"""Read-only Linux resource snapshots using procfs and sysfs."""

from datetime import datetime, timezone
from pathlib import Path
from shutil import disk_usage

from pydantic import BaseModel, ConfigDict, Field


class ResourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cpu_percent: float | None = Field(default=None, ge=0)
    memory_used_mb: int | None = Field(default=None, ge=0)
    memory_available_mb: int | None = Field(default=None, ge=0)
    swap_used_mb: int | None = Field(default=None, ge=0)
    disk_free_mb: int | None = Field(default=None, ge=0)
    process_count: int | None = Field(default=None, ge=0)
    temperatures_c: dict[str, float] = Field(default_factory=dict)


def _memory_values() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, raw_value = line.split(":", 1)
            values[key] = int(raw_value.strip().split()[0]) // 1024
    except (FileNotFoundError, ValueError):
        return {}
    return values


def _temperatures() -> dict[str, float]:
    result: dict[str, float] = {}
    for path in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        try:
            result[path.parent.name] = int(path.read_text().strip()) / 1000
        except (OSError, ValueError):
            continue
    return result


def capture_snapshot(root: Path = Path(".")) -> ResourceSnapshot:
    memory = _memory_values()
    disk_free_mb: int | None = None
    try:
        disk_free_mb = int(disk_usage(root).free / 1024 / 1024)
    except OSError:
        disk_free_mb = None
    process_count = None
    try:
        process_count = sum(entry.is_dir() and entry.name.isdigit() for entry in Path("/proc").iterdir())
    except OSError:
        pass
    total = memory.get("MemTotal")
    available = memory.get("MemAvailable")
    return ResourceSnapshot(
        memory_used_mb=total - available if total is not None and available is not None else None,
        memory_available_mb=available,
        swap_used_mb=(memory.get("SwapTotal", 0) - memory.get("SwapFree", 0)),
        disk_free_mb=disk_free_mb,
        process_count=process_count,
        temperatures_c=_temperatures(),
    )