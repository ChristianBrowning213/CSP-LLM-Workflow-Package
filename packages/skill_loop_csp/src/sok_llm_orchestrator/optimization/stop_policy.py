from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class StopDecision:
    stop: bool
    reason: str | None


def evaluate_stop_policy(
    *,
    budget_exhausted_reason: str | None,
    stuck_reason: str | None,
    target_threshold: float | None,
    best_score: float | None,
    user_requested_stop: bool = False,
) -> StopDecision:
    if user_requested_stop:
        return StopDecision(True, "user_requested_stop")
    if budget_exhausted_reason:
        return StopDecision(True, budget_exhausted_reason)
    if target_threshold is not None and isinstance(best_score, (int, float)) and best_score >= target_threshold:
        return StopDecision(True, "target_threshold_reached")
    return StopDecision(False, None)
