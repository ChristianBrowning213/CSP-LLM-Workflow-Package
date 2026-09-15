from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MidloopClarificationDecision:
    should_trigger: bool
    reason: str | None
    question: str | None
    blocking: bool
    deferred: bool
    assumption: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "should_trigger": self.should_trigger,
            "reason": self.reason,
            "question": self.question,
            "blocking": self.blocking,
            "deferred": self.deferred,
            "assumption": self.assumption,
        }


def evaluate_midloop_clarification(
    *,
    recent_iterations: list[dict[str, object]],
    stagnation_window: int,
    max_repeated_infeasible: int,
    ambiguity_between_families: bool = False,
    min_improvement_delta: float = 1e-9,
) -> MidloopClarificationDecision:
    if not recent_iterations:
        return MidloopClarificationDecision(False, None, None, False, False, None)

    if ambiguity_between_families:
        return MidloopClarificationDecision(
            True,
            "action_family_ambiguity",
            "Two optimization action families are similarly promising but imply different tradeoffs. Which should I prioritize?",
            False,
            True,
            "Proceed with balanced action-family exploration until chemist preference is provided.",
        )

    window = max(1, int(stagnation_window))
    latest = recent_iterations[-window:]
    infeasible = sum(1 for item in latest if not bool(item.get("feasible", True)))
    if infeasible >= max(1, int(max_repeated_infeasible)):
        return MidloopClarificationDecision(
            True,
            "repeated_infeasibility",
            "Recent iterations were repeatedly infeasible. Can I relax symmetry hardness or broaden retrieval constraints?",
            True,
            False,
            None,
        )

    objectives = [
        float(item["primary_objective"])
        for item in latest
        if isinstance(item.get("primary_objective"), (int, float))
    ]
    if len(objectives) >= window:
        if max(objectives) - min(objectives) <= min_improvement_delta:
            return MidloopClarificationDecision(
                True,
                "stagnation",
                "Optimization has stagnated. Should I prioritize broader exploration or tighten constraints around your target?",
                False,
                True,
                "Temporarily increase exploration and prioritize non-baseline families while waiting for clarification.",
            )
    return MidloopClarificationDecision(False, None, None, False, False, None)
