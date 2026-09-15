from __future__ import annotations

from typing import Any, Mapping

from .schemas import assert_json_serializable, to_json_dict

PARTIAL_SUCCESS_SCHEMA_VERSION = "agentic_csp.partial_success.v1"
CONTINUATION_SUMMARY_SCHEMA_VERSION = "agentic_csp.continuation_summary.v1"


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    return default


def build_partial_success_evaluation(
    replay_result: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(replay_result, Mapping):
        msg = "replay_result must be a mapping"
        raise TypeError(msg)

    replay_dict = to_json_dict(replay_result)
    failure_handling = (
        to_json_dict(replay_dict["failure_handling"])
        if isinstance(replay_dict.get("failure_handling"), Mapping)
        else {}
    )
    actions = (
        [
            to_json_dict(item)
            for item in failure_handling.get("actions", [])
            if isinstance(item, Mapping)
        ]
        if isinstance(failure_handling.get("actions"), list)
        else []
    )
    failure_status = _safe_string(failure_handling, "status")

    continuation_plan: list[dict[str, Any]] = []
    blocked_dependencies: list[str] = []
    optional_stages_skipped: list[str] = []
    recovery_paths: list[str] = []
    warnings: list[str] = []

    status = "continue_allowed"
    for index, action in enumerate(actions):
        action_type = _safe_string(action, "action_type", "continue")
        tool_name = _safe_string(action, "tool_name", f"step_{index}")
        step_index = int(action.get("source_step_index", index))
        continuation_decision = "continue"
        reason = _safe_string(action, "reason", "No action required.")

        if action_type == "block_next_stage":
            continuation_decision = "blocked"
            status = "blocked"
            if tool_name not in blocked_dependencies:
                blocked_dependencies.append(tool_name)
        elif action_type in {
            "recompile_request",
            "fallback_retrieval",
            "repackage_qlip_request",
            "repair_spp_qlip_package",
            "revise_qlip_formulation",
        }:
            continuation_decision = "recovery_required"
            if status != "blocked":
                status = "continue_with_warnings"
            if tool_name not in recovery_paths:
                recovery_paths.append(tool_name)
        elif action_type == "skip_optional_stage":
            continuation_decision = "continue_optional_path"
            if status != "blocked":
                status = "continue_with_warnings"
            if tool_name not in optional_stages_skipped:
                optional_stages_skipped.append(tool_name)

        continuation_plan.append(
            {
                "step_index": step_index,
                "tool_name": tool_name,
                "continuation_decision": continuation_decision,
                "reason": reason,
            }
        )

    if failure_status == "blocked" and not blocked_dependencies:
        blocked_dependencies.extend(
            [
                str(item)
                for item in failure_handling.get("blocked_reasons", [])
                if str(item).strip()
            ]
            if isinstance(failure_handling.get("blocked_reasons"), list)
            else []
        )
        status = "blocked"

    if blocked_dependencies:
        warnings.append(
            "Blocked dependencies: " + ", ".join(blocked_dependencies)
        )
    if optional_stages_skipped:
        warnings.append(
            "Optional stages skipped: " + ", ".join(optional_stages_skipped)
        )
    if recovery_paths:
        warnings.append(
            "Recovery paths required for: " + ", ".join(recovery_paths)
        )

    result = {
        "schema_version": PARTIAL_SUCCESS_SCHEMA_VERSION,
        "route_mode": _safe_string(replay_dict, "route_mode"),
        "source_run_id": _safe_string(replay_dict, "source_run_id"),
        "status": status,
        "continuation_plan": continuation_plan,
        "blocked_dependencies": blocked_dependencies,
        "optional_stages_skipped": optional_stages_skipped,
        "recovery_paths": recovery_paths,
        "warnings": warnings,
    }
    assert_json_serializable(result)
    return result


def build_continuation_summary(
    partial_success_result: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(partial_success_result, Mapping):
        msg = "partial_success_result must be a mapping"
        raise TypeError(msg)

    partial_dict = to_json_dict(partial_success_result)
    continuation_plan = (
        [
            to_json_dict(item)
            for item in partial_dict.get("continuation_plan", [])
            if isinstance(item, Mapping)
        ]
        if isinstance(partial_dict.get("continuation_plan"), list)
        else []
    )

    continued_steps: list[str] = []
    skipped_steps: list[str] = []
    blocked_steps: list[str] = []
    recovery_steps: list[str] = []

    for step in continuation_plan:
        tool_name = _safe_string(step, "tool_name")
        decision = _safe_string(step, "continuation_decision")
        if decision == "continue":
            continued_steps.append(tool_name)
        elif decision in {"continue_optional_path", "skipped_optional_stage"}:
            skipped_steps.append(tool_name)
        elif decision == "blocked":
            blocked_steps.append(tool_name)
        elif decision == "recovery_required":
            recovery_steps.append(tool_name)

    final_status = _safe_string(partial_dict, "status")
    if final_status == "continue_allowed":
        summary_text = "All replay steps remain eligible to continue."
    elif final_status == "continue_with_warnings":
        parts: list[str] = []
        if skipped_steps:
            parts.append("skipped optional stages: " + ", ".join(skipped_steps))
        if recovery_steps:
            parts.append("recovery required: " + ", ".join(recovery_steps))
        summary_text = "Continuation allowed with warnings: " + "; ".join(parts) + "."
    else:
        summary_text = "Continuation blocked by: " + ", ".join(blocked_steps)

    result = {
        "schema_version": CONTINUATION_SUMMARY_SCHEMA_VERSION,
        "final_status": final_status,
        "continued_steps": continued_steps,
        "skipped_steps": skipped_steps,
        "blocked_steps": blocked_steps,
        "recovery_steps": recovery_steps,
        "summary_text": summary_text,
    }
    assert_json_serializable(result)
    return result


__all__ = [
    "PARTIAL_SUCCESS_SCHEMA_VERSION",
    "CONTINUATION_SUMMARY_SCHEMA_VERSION",
    "build_partial_success_evaluation",
    "build_continuation_summary",
]
