from __future__ import annotations

from sok_llm_orchestrator.optimization.planner import build_optimization_plan


def test_optimization_planner_emits_valid_plan() -> None:
    plan = build_optimization_plan(
        task_spec={
            "composition_target": "TiO2",
            "property_bias": "property_x",
            "symmetry_request": {"space_group": "P42/mnm", "hardness": "soft"},
        },
        max_iterations=4,
        exploration_rate=0.3,
        stagnation_window=2,
    )
    payload = plan.to_dict()
    assert payload["schema_version"] == "optimization.plan.v1"
    assert payload["exploration_strategy"]["exploration_rate"] == 0.3

