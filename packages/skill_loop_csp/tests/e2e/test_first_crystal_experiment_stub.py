from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.first_crystal import run_first_crystal_experiment


def test_first_crystal_experiment_stub(workdir: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    root = Path(__file__).resolve().parents[2]
    cases = root / "tests" / "fixtures" / "optimization" / "first_crystal_case_set.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_allow_midloop_clarification = False
    result = run_first_crystal_experiment(
        case_file=cases,
        mode="stub",
        workspace=workdir,
        settings=settings,
        max_iterations=2,
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["schema_version"] == "first_crystal.summary.v1"
    assert summary["rows"]
    row = summary["rows"][0]
    assert {"initial_score", "final_best_score", "improvement_delta", "stop_reason", "best_iteration_index", "best_action_id", "best_structure_artifact_path"}.issubset(
        row.keys()
    )
    assert isinstance(row["best_structure_artifact_path"], str)
