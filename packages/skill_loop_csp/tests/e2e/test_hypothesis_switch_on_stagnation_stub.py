from __future__ import annotations

from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def _stagnant(_: str, __: dict[str, Any]) -> dict[str, Any]:
    return {
        "feasible": True,
        "primary_objective": 0.12,
        "property_estimate": 0.12,
        "valid_for_learning": True,
        "solver_calls": 1,
        "retrieval_calls": 1,
        "run_reference": {},
    }


def test_hypothesis_switch_on_stagnation_stub(workdir) -> None:  # type: ignore[no-untyped-def]
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 5
    settings.optimization_stagnation_window = 2
    settings.optimization_allow_midloop_clarification = False
    settings.optimization_exploration_rate = 0.0
    engine = OptimizationEngine(workspace=workdir, settings=settings, mode="stub", executor=_stagnant)
    meta = {
        "case_id": "switch_case",
        "hypotheses": [
            {"hypothesis_id": "h1", "label": "ordered", "hypothesis_family": "ordering_sensitive"},
            {"hypothesis_id": "h2", "label": "relaxed", "hypothesis_family": "template_relaxed"},
            {"hypothesis_id": "h3", "label": "framework", "hypothesis_family": "framework_broad"},
        ],
    }
    result = engine.start(query="Na3Zr2Si2PO12 optimize", auto_run=True, case_metadata=meta)
    session = engine.get(result.session_id)
    events = session.hypothesis_state.get("switch_events", [])
    assert isinstance(events, list) and len(events) >= 1
    first = events[0]
    assert first["from_hypothesis_id"] == "h1"
    assert first["to_hypothesis_id"] in {"h2", "h3"}
