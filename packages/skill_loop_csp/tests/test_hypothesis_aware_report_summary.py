from __future__ import annotations

from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine
from sok_llm_orchestrator.optimization.reporting import build_optimization_report


def _executor(_: str, __: dict[str, Any]) -> dict[str, Any]:
    return {
        "feasible": True,
        "primary_objective": 0.33,
        "property_estimate": 0.33,
        "valid_for_learning": True,
        "solver_calls": 1,
        "retrieval_calls": 1,
        "run_reference": {},
    }


def test_hypothesis_aware_report_summary_fields(workdir) -> None:  # type: ignore[no-untyped-def]
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 4
    settings.optimization_stagnation_window = 2
    settings.optimization_allow_midloop_clarification = False
    settings.optimization_exploration_rate = 0.0
    engine = OptimizationEngine(workspace=workdir, settings=settings, mode="stub", executor=_executor)
    meta = {
        "case_id": "report_case",
        "hypotheses": [
            {"hypothesis_id": "ha", "label": "a", "hypothesis_family": "perovskite_cubic"},
            {"hypothesis_id": "hb", "label": "b", "hypothesis_family": "template_relaxed"},
        ],
    }
    result = engine.start(query="BaTiO3 optimize", auto_run=True, case_metadata=meta)
    session = engine.get(result.session_id)
    report = build_optimization_report(session)
    summary = report["hypothesis_branch_summary"]

    assert "hypotheses_tried" in summary
    assert set(summary["hypotheses_tried"]) >= {"ha", "hb"}
    assert int(summary["branch_switch_count"]) >= 1
    assert isinstance(summary.get("active_hypothesis_by_iteration"), list)
    assert len(summary["active_hypothesis_by_iteration"]) == report["iteration_count"]
    assert isinstance(summary.get("rows"), list) and summary["rows"]
    assert report["diagnostics"]["branch_switch_count"] >= 1
