from __future__ import annotations

from typing import Any, Mapping

from .schemas import assert_json_serializable, to_json_dict

STEP_EXECUTION_PLAN_SCHEMA_VERSION = "agentic_csp.step_execution_plan.v1"
NOOP_STEP_EXECUTION_SCHEMA_VERSION = "agentic_csp.noop_step_execution.v1"


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    return default


def build_step_execution_plan(execution_handoff: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(execution_handoff, Mapping):
        msg = "execution_handoff must be a mapping"
        raise TypeError(msg)

    handoff_dict = to_json_dict(execution_handoff)
    selected_proposals = handoff_dict.get("selected_proposals")
    proposal_list = (
        [to_json_dict(item) for item in selected_proposals if isinstance(item, Mapping)]
        if isinstance(selected_proposals, list)
        else []
    )
    warnings = handoff_dict.get("warnings")
    warning_list = (
        [str(item) for item in warnings if str(item).strip()]
        if isinstance(warnings, list)
        else []
    )
    blocked_reasons = handoff_dict.get("blocked_reasons")
    blocked_reason_list = (
        [str(item) for item in blocked_reasons if str(item).strip()]
        if isinstance(blocked_reasons, list)
        else []
    )

    handoff_ready = (
        _safe_string(handoff_dict, "status") == "ready"
        and handoff_dict.get("execution_allowed") is True
    )
    if not handoff_ready:
        result = {
            "schema_version": STEP_EXECUTION_PLAN_SCHEMA_VERSION,
            "status": "blocked",
            "steps": [],
            "blocked_reasons": blocked_reason_list,
            "warnings": warning_list,
        }
        assert_json_serializable(result)
        return result

    steps: list[dict[str, Any]] = []
    for index, proposal in enumerate(proposal_list):
        steps.append(
            {
                "step_index": index,
                "tool_name": _safe_string(proposal, "tool_name"),
                "proposal": proposal,
                "expected_mode": "noop_dry_run",
                "status": "pending",
            }
        )

    result = {
        "schema_version": STEP_EXECUTION_PLAN_SCHEMA_VERSION,
        "status": "ready",
        "steps": steps,
        "blocked_reasons": [],
        "warnings": warning_list,
    }
    assert_json_serializable(result)
    return result


def run_noop_step_execution(
    step_execution_plan: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(step_execution_plan, Mapping):
        msg = "step_execution_plan must be a mapping"
        raise TypeError(msg)

    plan_dict = to_json_dict(step_execution_plan)
    warnings = plan_dict.get("warnings")
    warning_list = (
        [str(item) for item in warnings if str(item).strip()]
        if isinstance(warnings, list)
        else []
    )
    blocked_reasons = plan_dict.get("blocked_reasons")
    blocked_reason_list = (
        [str(item) for item in blocked_reasons if str(item).strip()]
        if isinstance(blocked_reasons, list)
        else []
    )

    if _safe_string(plan_dict, "status") != "ready":
        result = {
            "schema_version": NOOP_STEP_EXECUTION_SCHEMA_VERSION,
            "execution_performed": False,
            "status": "blocked",
            "step_results": [],
            "blocked_reasons": blocked_reason_list,
            "warnings": warning_list,
        }
        assert_json_serializable(result)
        return result

    steps = plan_dict.get("steps")
    step_list = (
        [to_json_dict(item) for item in steps if isinstance(item, Mapping)]
        if isinstance(steps, list)
        else []
    )
    step_results = [
        {
            "step_index": int(step.get("step_index", index)),
            "tool_name": _safe_string(step, "tool_name"),
            "status": "would_execute",
            "result_summary": "noop dry run only",
        }
        for index, step in enumerate(step_list)
    ]
    result = {
        "schema_version": NOOP_STEP_EXECUTION_SCHEMA_VERSION,
        "execution_performed": False,
        "status": "completed",
        "step_results": step_results,
        "blocked_reasons": [],
        "warnings": warning_list,
    }
    assert_json_serializable(result)
    return result


__all__ = [
    "NOOP_STEP_EXECUTION_SCHEMA_VERSION",
    "STEP_EXECUTION_PLAN_SCHEMA_VERSION",
    "build_step_execution_plan",
    "run_noop_step_execution",
]
