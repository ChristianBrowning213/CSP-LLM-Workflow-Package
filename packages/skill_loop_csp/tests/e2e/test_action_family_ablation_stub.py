from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.ablation import validate_compiled_action_surface
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
    action = str(compiled["action_id"])
    base = 0.1
    if action == "guided_hybrid_balanced":
        base = 0.6
    elif action == "guided_property_push":
        base = 0.5
    return {
        "feasible": True,
        "primary_objective": base,
        "property_estimate": base,
        "valid_for_learning": True,
        "solver_calls": 2,
        "retrieval_calls": 2,
        "run_reference": {"action": action},
    }


def _run_once(workspace: Path) -> list[dict[str, Any]]:
    settings = Settings.from_sources(None)
    settings.workspace_root = workspace
    settings.optimization_exploration_rate = 1.0
    settings.optimization_max_iterations = 6
    settings.optimization_allow_midloop_clarification = False
    settings.optimization_stagnation_window = 10
    engine = OptimizationEngine(
        workspace=workspace,
        settings=settings,
        mode="stub",
        executor=_executor,
    )
    start = engine.start(query="TiO2 optimize high property x", auto_run=True)
    report = json.loads((start.session_path.parent / "report.json").read_text(encoding="utf-8"))
    session = engine.get(start.session_id)
    for item in session.iteration_history:
        validate_compiled_action_surface(item["compiled_action"])
    return list(report["action_ablation_trace"])


def test_action_family_ablation_e2e_stub(workdir: Path) -> None:
    trace1 = _run_once(workdir / "w1")
    trace2 = _run_once(workdir / "w2")
    assert trace1
    assert trace1 == trace2
    assert any(entry["delta"]["category"] in {"bundled/full-action change", "no_change"} for entry in trace1[1:])

