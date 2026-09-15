from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.experiments.first_crystal import run_first_crystal_experiment


def _executor_factory(workdir: Path):  # type: ignore[no-untyped-def]
    def _build(case: dict[str, Any]):  # type: ignore[no-untyped-def]
        case_id = str(case["case_id"])
        case_class = str(case.get("case_class") or "easy-improvement")
        seen: dict[str, int] = {}

        def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
            action = str(compiled["action_id"])
            idx = seen.get(action, 0)
            seen[action] = idx + 1
            structure = workdir / "synthetic_structures" / case_id / f"{action}_{idx}.cif"
            structure.parent.mkdir(parents=True, exist_ok=True)
            structure.write_text(f"data_{case_id}_{action}_{idx}\n", encoding="utf-8")

            feasible = True
            value = 0.1
            if case_class == "easy-improvement":
                value = 0.7 if action == "guided_hybrid_balanced" else 0.2
            elif case_class == "flat-stagnant":
                value = 0.3
            elif case_class == "repeated-infeasible":
                feasible = False
                value = 0.0
            return {
                "feasible": feasible,
                "primary_objective": value,
                "property_estimate": value if feasible else None,
                "valid_for_learning": feasible,
                "solver_calls": 2,
                "retrieval_calls": 2,
                "run_reference": {
                    "case_id": case_id,
                    "structure_artifact_path": str(structure),
                },
            }

        return _run

    return _build


def test_first_crystal_experiment_runner(workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    case_file = root / "docs" / "branch" / "benchmarks" / "first_crystal_cases.json"
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_allow_midloop_clarification = False
    result = run_first_crystal_experiment(
        case_file=case_file,
        mode="stub",
        workspace=workdir,
        settings=settings,
        max_iterations=3,
        executor_factory=_executor_factory(workdir),
    )
    manifest_path = Path(result["manifest_path"])
    summary_path = Path(result["summary_path"])
    assert manifest_path.exists()
    assert summary_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "first_crystal.experiment.v1"
    assert summary["schema_version"] == "first_crystal.summary.v1"
    assert len(summary["rows"]) == len(manifest["cases"])
    assert summary["rows"]
    assert {"case_id", "session_id", "initial_score", "final_best_score", "improvement_delta", "stop_reason", "best_action_id", "best_structure_artifact_path"}.issubset(
        summary["rows"][0].keys()
    )
    assert any(
        isinstance(row.get("best_structure_artifact_path"), str)
        and Path(str(row["best_structure_artifact_path"])).exists()
        for row in summary["rows"]
    )

