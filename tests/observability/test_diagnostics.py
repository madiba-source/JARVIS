from app.observability.config import ObservabilityConfig
from app.observability.diagnostics import DiagnosticsCollector


def test_diagnostics_reports_real_subsystems(tmp_path) -> None:
    config = ObservabilityConfig(log_directory=tmp_path / "logs", sqlite_path=tmp_path / "events.db", tracing_enabled=False)
    diagnostics = DiagnosticsCollector(config=config)
    report = diagnostics.collect()
    assert report["tracing"] == "disabled"
    assert report["sqlite"] == "ok"
    assert "environment" not in report
    diagnostics.store.close()
