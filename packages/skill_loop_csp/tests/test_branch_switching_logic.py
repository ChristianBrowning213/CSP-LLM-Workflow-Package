from __future__ import annotations

from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine
from sok_llm_orchestrator.optimization.reporting import build_optimization_report


def _flat_executor(_: str, __: dict[str, Any]) -> dict[str, Any]:
    return {
        "feasible": True,
        "primary_objective": 0.25,
        "property_estimate": 0.25,
        "valid_for_learning": True,
        "solver_calls": 1,
        "retrieval_calls": 1,
        "run_reference": {},
    }


def test_branch_switching_logic_switches_on_stagnation(workdir) -> None:  # type: ignore[no-untyped-def]
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 5
    settings.optimization_stagnation_window = 2
    settings.optimization_allow_midloop_clarification = False
    settings.optimization_exploration_rate = 0.0
    engine = OptimizationEngine(workspace=workdir, settings=settings, mode="stub", executor=_flat_executor)
    case_metadata = {
        "case_id": "mh_switch_case",
        "hypotheses": [
            {"hypothesis_id": "h_ordered", "label": "ordered", "hypothesis_family": "double_perovskite_ordered"},
            {"hypothesis_id": "h_relaxed", "label": "relaxed", "hypothesis_family": "template_relaxed"},
        ],
    }
    result = engine.start(query="Sr2FeMoO6 optimize", auto_run=True, case_metadata=case_metadata)
    session = engine.get(result.session_id)
    report = build_optimization_report(session)
    summary = report["hypothesis_branch_summary"]
    assert int(summary["branch_switch_count"]) >= 1
    tried = set(summary["hypotheses_tried"])
    assert {"h_ordered", "h_relaxed"}.issubset(tried)
    assert isinstance(summary.get("best_hypothesis_id"), str)
