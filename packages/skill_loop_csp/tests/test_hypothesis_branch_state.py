from __future__ import annotations

from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def _stagnant_executor(_: str, __: dict[str, Any]) -> dict[str, Any]:
    return {
        "feasible": True,
        "primary_objective": 0.2,
        "property_estimate": 0.2,
        "valid_for_learning": True,
        "solver_calls": 1,
        "retrieval_calls": 1,
        "run_reference": {},
    }


def test_hypothesis_branch_state_tracks_active_tried_and_history(workdir) -> None:  # type: ignore[no-untyped-def]
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 4
    settings.optimization_stagnation_window = 2
    settings.optimization_allow_midloop_clarification = False
    settings.optimization_exploration_rate = 0.0
    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        executor=_stagnant_executor,
    )
    case_metadata = {
        "case_id": "mh_stub_case",
        "hypotheses": [
            {"hypothesis_id": "h1", "label": "first", "hypothesis_family": "perovskite_cubic"},
            {"hypothesis_id": "h2", "label": "second", "hypothesis_family": "template_relaxed"},
        ],
    }
    result = engine.start(
        query="SrTiO3 optimize high property x",
        auto_run=True,
        case_metadata=case_metadata,
    )
    session = engine.get(result.session_id)
    state = session.hypothesis_state
    assert state.get("available_hypotheses")
    assert state.get("tried_hypothesis_ids")
    assert isinstance(state.get("branch_history"), list)
    assert len(state["branch_history"]) == len(session.iteration_history)
    assert isinstance(state.get("branch_best"), dict)
    assert "h1" in state["tried_hypothesis_ids"]
    assert "h2" in state["tried_hypothesis_ids"]
    assert isinstance(state.get("switch_events"), list) and len(state["switch_events"]) >= 1
