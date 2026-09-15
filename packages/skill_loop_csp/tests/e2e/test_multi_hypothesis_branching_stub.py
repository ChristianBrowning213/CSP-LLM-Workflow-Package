from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.first_crystal import run_first_crystal_experiment


def _executor_factory(_: dict[str, Any]):  # type: ignore[no-untyped-def]
    def _run(__: str, ___: dict[str, Any]) -> dict[str, Any]:
        return {
            "feasible": True,
            "primary_objective": 0.3,
            "property_estimate": 0.3,
            "valid_for_learning": True,
            "solver_calls": 1,
            "retrieval_calls": 1,
            "run_reference": {},
        }

    return _run


def test_multi_hypothesis_branching_stub(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    case_file = root / "docs" / "branch" / "benchmarks" / "multi_hypothesis_complex_cases.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 4
    settings.optimization_stagnation_window = 2
    settings.optimization_allow_midloop_clarification = False
    settings.optimization_exploration_rate = 0.0
    out = run_first_crystal_experiment(
        case_file=case_file,
        mode="stub",
        workspace=workdir,
        settings=settings,
        max_iterations=4,
        executor_factory=_executor_factory,
    )
    summary = json.loads(Path(out["summary_path"]).read_text(encoding="utf-8"))
    rows = summary["rows"]
    assert rows
    assert any(len(row.get("hypotheses_tried", [])) >= 2 for row in rows)
    assert any(int(row.get("branch_switch_count", 0) or 0) >= 1 for row in rows)
