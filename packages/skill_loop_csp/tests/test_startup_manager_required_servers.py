from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.startup import required_startup_dependencies, run_startup_validation


def test_startup_manager_required_servers(monkeypatch, workdir: Path) -> None:  # type: ignore[no-untyped-def]
    seen: list[str] = []

    def _fake_run_dependency(**kwargs):  # type: ignore[no-untyped-def]
        dep = str(kwargs["dependency"])
        seen.append(dep)
        return {
            "dependency": dep,
            "command": kwargs["command"],
            "startup_ok": True,
            "surface_ok": True,
            "semantic_ok": True,
            "ok": True,
            "failure_code": None,
            "detail": "ok",
            "probe": {"stub": True},
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
    assert report["startup_ok"] is True
    assert set(seen) == set(required_startup_dependencies())
