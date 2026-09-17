from typing import Any

from .diagnostics import DiagnosticsCollector


class HealthChecker:
    @staticmethod
    def check(collector: DiagnosticsCollector | None = None) -> dict[str, Any]:
        status = (collector or DiagnosticsCollector()).collect()
        states = [status["logging"], status["metrics"], status["tracing"], status["sqlite"]]
        overall = "failed" if "failed" in states else ("degraded" if "degraded" in states else "ok")
        return {**status, "overall": overall}
