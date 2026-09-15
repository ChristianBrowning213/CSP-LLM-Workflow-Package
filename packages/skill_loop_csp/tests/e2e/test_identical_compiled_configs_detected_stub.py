from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.action_compile import CompiledOptimizationAction
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def _flat_executor(workdir: Path):  # type: ignore[no-untyped-def]
    def _run(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
        action = str(compiled["action_id"])
        structure = workdir / "identical_config_structures" / f"{action}.cif"
        structure.parent.mkdir(parents=True, exist_ok=True)
        structure.write_text(f"data_{action}\n", encoding="utf-8")
        return {
            "feasible": True,
            "primary_objective": 0.2,
            "property_estimate": 0.2,
            "valid_for_learning": True,
            "solver_calls": 1,
            "retrieval_calls": 1,
            "run_reference": {"structure_artifact_path": str(structure)},
        }

    return _run


def test_identical_compiled_configs_are_detected(workdir: Path, monkeypatch: Any) -> None:
    import sok_llm_orchestrator.optimization.loop as loop_mod

    def _constant_compile(action: Any) -> CompiledOptimizationAction:
        return CompiledOptimizationAction(
            action_id=str(action.action_id),
            action_family=str(action.action_family),
            compiled_id="optcfg-constant",
            execution_mode="paired",
            query_suffix="",
            guided_with_spp=True,
            baseline_overrides={
                "retrieval_mode": "metadata",
                "corpus_strategy": "composition_tight",
                "guidance_mode": "none",
                "verification_preset": "benchmark",
                "cell_selection_policy": "baseline_default",
                "spp_calibration_mode": "conservative",
            },
            guided_overrides={
                "retrieval_mode": "metadata",
                "corpus_strategy": "composition_tight",
                "guidance_mode": "guidance_only",
                "verification_preset": "benchmark",
                "cell_selection_policy": "baseline_default",
                "spp_calibration_mode": "conservative",
            },
        )

    monkeypatch.setattr(loop_mod, "compile_action", _constant_compile)
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 4
    settings.optimization_exploration_rate = 0.0
    settings.optimization_allow_midloop_clarification = False
    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        executor=_flat_executor(workdir),
    )
    result = engine.start(query="TiO2 optimize high property x", auto_run=True)
    report = json.loads((result.session_path.parent / "report.json").read_text(encoding="utf-8"))
    diag = report["diagnostics"]
    assert diag["unique_action_id_count"] > 1
    assert diag["unique_compiled_config_signature_count"] == 1
    assert diag["flat_objective_flag"] is True
    assert diag["likely_flatness_reason"] == "different_actions_same_effective_config"
