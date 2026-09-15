from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.first_crystal import run_first_crystal_experiment


def test_first_crystal_with_supplied_clarification_answers_runs_and_logs_answers(workdir: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    root = Path(__file__).resolve().parents[2]
    cases = root / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 3
    settings.optimization_stagnation_window = 2
    settings.optimization_allow_midloop_clarification = True

    answers = ["treat symmetry as soft", "keep objective-driven search"]
    result = run_first_crystal_experiment(
        case_file=cases,
        mode="stub",
        workspace=workdir,
        settings=settings,
        max_iterations=3,
        clarification_answers=answers,
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    row = summary["rows"][0]

    assert row["clarification_answers"] == answers
    assert manifest["clarification_answers"] == answers
    assert row["stop_reason"] != "midloop_clarification_required"
    assert isinstance(row["best_structure_artifact_path"], str)
