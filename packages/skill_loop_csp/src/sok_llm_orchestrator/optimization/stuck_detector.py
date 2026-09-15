from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class StuckState:
    stuck: bool
    reason: str | None
    metrics: dict[str, Any]


def detect_stuck(
    iteration_history: list[dict[str, Any]],
    *,
    stagnation_window: int,
    min_improvement_delta: float = 1e-9,
    repeated_infeasible_limit: int = 3,
) -> StuckState:
    if not iteration_history:
        return StuckState(False, None, {"history": 0})

    recent = iteration_history[-max(1, stagnation_window) :]
    infeasible_count = sum(1 for row in recent if not bool(row.get("feasible", False)))
    if infeasible_count >= max(1, repeated_infeasible_limit):
        return StuckState(
            True,
            "repeated_infeasibility",
            {"window": len(recent), "infeasible_count": infeasible_count},
        )

    values = [float(row["primary_objective"]) for row in recent if isinstance(row.get("primary_objective"), (int, float))]
    if len(values) >= max(2, stagnation_window):
        if max(values) - min(values) <= min_improvement_delta:
            return StuckState(
                True,
                "stagnation",
                {"window": len(recent), "objective_span": max(values) - min(values)},
            )
    return StuckState(False, None, {"window": len(recent)})

