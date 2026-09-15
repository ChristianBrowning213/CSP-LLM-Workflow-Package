from __future__ import annotations

from sok_llm_orchestrator.optimization.plan_schema import OptimizationPlan, validate_optimization_plan


def test_optimization_plan_schema_valid() -> None:
    plan = OptimizationPlan(
        objective_target="Improve objective",
        initial_hypotheses=["h1"],
        action_family_priorities=["guided_exploit"],
        exploration_strategy={"policy": "epsilon_greedy", "exploration_rate": 0.2},
        stopping_criteria={"max_iterations": 5},
        fallback_strategy=["fallback"],
        escalation_conditions=["stagnation"],
    )
    validate_optimization_plan(plan.to_dict())

