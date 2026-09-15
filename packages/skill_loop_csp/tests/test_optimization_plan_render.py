from __future__ import annotations

from sok_llm_orchestrator.optimization.plan_render import render_optimization_plan
from sok_llm_orchestrator.optimization.planner import build_optimization_plan


def test_plan_render_matches_plan_fields() -> None:
    plan = build_optimization_plan(
        task_spec={"composition_target": "TiO2", "property_bias": None, "symmetry_request": {"space_group": None}},
        max_iterations=3,
        exploration_rate=0.25,
        stagnation_window=2,
    )
    text = render_optimization_plan(plan)
    assert "Objective:" in text
    assert "Action family priorities:" in text
    assert "Exploration:" in text

