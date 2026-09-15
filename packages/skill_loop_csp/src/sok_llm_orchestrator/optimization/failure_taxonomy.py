from __future__ import annotations

from typing import Any


def _detect_oscillation(iteration_trace: list[dict[str, Any]]) -> bool:
    if len(iteration_trace) < 4:
        return False
    fam = [str(item.get("action_family", "")) for item in iteration_trace[-4:]]
    return fam[0] == fam[2] and fam[1] == fam[3] and fam[0] != fam[1]


def classify_failure_taxonomy(
    *,
    status: str,
    termination_reason: str | None,
    blocked_state: dict[str, Any] | None,
    iteration_trace: list[dict[str, Any]],
) -> dict[str, Any]:
    categories: set[str] = set()
    if termination_reason and termination_reason.startswith("budget_exhausted:"):
        categories.add("budget_exhaustion")
    if termination_reason in {"midloop_clarification_required", "stop_hook_clarification_required"}:
        categories.add("blocked-clarification-needed")
    if termination_reason == "stop_hook_exhausted":
        categories.add("budget_exhaustion")
    if blocked_state:
        reason = str(blocked_state.get("reason", ""))
        if reason == "stagnation":
            categories.add("stagnation")
        if reason == "repeated_infeasibility":
            categories.add("repeated_infeasibility")
    if any(
        bool(item.get("arbitration", {}).get("gate", {}).get("via_fallback"))
        and item.get("arbitration", {}).get("llm_proposal", {}).get("action_id") is not None
        for item in iteration_trace
    ):
        categories.add("invalid-action rejection")
    if _detect_oscillation(iteration_trace):
        categories.add("oscillation")
    if not categories and status in {"STOPPED", "FAILED"}:
        categories.add("unclassified")

    priority = [
        "repeated_infeasibility",
        "stagnation",
        "invalid-action rejection",
        "budget_exhaustion",
        "blocked-clarification-needed",
        "oscillation",
        "unclassified",
    ]
    primary = next((item for item in priority if item in categories), "none")
    recommendations = {
        "repeated_infeasibility": "run_recovery_ladder_then_consider_clarification",
        "stagnation": "increase_exploration_or_request_midloop_guidance",
        "invalid-action rejection": "continue_with_policy_fallback_and_log",
        "budget_exhaustion": "stop_or_increase_budget",
        "blocked-clarification-needed": "await_chemist_input",
        "oscillation": "apply_action_family_limits_or_reduce_exploration",
        "unclassified": "inspect_iteration_trace",
        "none": "continue",
    }
    return {
        "primary_category": primary,
        "categories": [item for item in priority if item in categories],
        "termination_reason": termination_reason,
        "recommended_next_step": recommendations.get(primary, "inspect_iteration_trace"),
    }
