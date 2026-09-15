from __future__ import annotations

from sok_llm_orchestrator.optimization.plan_schema import OptimizationPlan


def render_optimization_plan(plan: OptimizationPlan) -> str:
    lines = [
        "Optimization Plan",
        f"Objective: {plan.objective_target}",
        "Initial hypotheses:",
    ]
    for item in plan.initial_hypotheses:
        lines.append(f"- {item}")
    lines.append(f"Action family priorities: {', '.join(plan.action_family_priorities)}")
    lines.append(
        "Exploration: "
        f"{plan.exploration_strategy.get('policy')} (rate={plan.exploration_strategy.get('exploration_rate')})"
    )
    lines.append(f"Stopping criteria: {plan.stopping_criteria}")
    lines.append(f"Fallback strategy: {', '.join(plan.fallback_strategy)}")
    lines.append(f"Escalation conditions: {', '.join(plan.escalation_conditions)}")
    return "\n".join(lines)

