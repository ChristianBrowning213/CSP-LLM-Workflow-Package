from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.startup import run_startup_validation


def test_startup_report_schema(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    def _fake_run_dependency(**kwargs):  # type: ignore[no-untyped-def]
        dep = str(kwargs["dependency"])
        return {
            "dependency": dep,
            "command": kwargs["command"],
            "startup_ok": True,
            "surface_ok": True,
            "semantic_ok": True,
            "ok": True,
            "failure_code": None,
            "detail": "ok",
            "probe": {"probe_name": dep},
        }

    monkeypatch.setattr("sok_llm_orchestrator.orchestrator.startup._run_dependency", _fake_run_dependency)
    settings = Settings.from_sources(None)
    report = run_startup_validation(
        mode="stub",
        settings=settings,
        workspace=workdir,
        commands=(["a"], ["b"], ["c"]),
        strict=True,
    )
    assert report["schema_version"] == "startup.report.v1"
    assert isinstance(report["dependencies"], dict)
    assert report["startup_ok"] is True
    artifacts = report["artifacts"]
    startup_report_path = Path(str(artifacts["startup_report"]))
    startup_probe_path = Path(str(artifacts["startup_probe_results"]))
    assert startup_report_path.exists()
    assert startup_probe_path.exists()
    on_disk = json.loads(startup_report_path.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == "startup.report.v1"
