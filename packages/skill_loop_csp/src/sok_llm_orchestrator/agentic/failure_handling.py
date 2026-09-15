from __future__ import annotations

from typing import Any, Mapping

from .schemas import assert_json_serializable, to_json_dict

FAILURE_HANDLING_SCHEMA_VERSION = "agentic_csp.failure_handling.v1"


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    return default


def _default_recovery_plan(action_type: str, hint: str) -> dict[str, Any]:
    return {
        "recovery_recommended": action_type != "continue",
        "action": action_type,
        "can_auto_retry": False,
        "requires_new_data": False,
        "requires_formulation_change": False,
        "recoverable": action_type != "continue",
        "recommended_action": action_type,
        "next_step_hint": hint,
        "hint": hint,
        "evidence_path": None,
    }


def handle_inspection_failures(
    result_inspection: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(result_inspection, Mapping):
        msg = "result_inspection must be a mapping"
        raise TypeError(msg)

    inspection_dict = to_json_dict(result_inspection)
    inspected_steps = inspection_dict.get("inspected_steps")
    step_list = (
        [to_json_dict(item) for item in inspected_steps if isinstance(item, Mapping)]
        if isinstance(inspected_steps, list)
        else []
    )
    warnings = inspection_dict.get("warnings")
    warning_list = (
        [str(item) for item in warnings if str(item).strip()]
        if isinstance(warnings, list)
        else []
    )
    blocked_reasons = inspection_dict.get("blocked_reasons")
    blocked_reason_list = (
        [str(item) for item in blocked_reasons if str(item).strip()]
        if isinstance(blocked_reasons, list)
        else []
    )

    inspection_status = _safe_string(inspection_dict, "status")
    if inspection_status == "blocked" and not step_list:
        result = {
            "schema_version": FAILURE_HANDLING_SCHEMA_VERSION,
            "status": "blocked",
            "actions": [],
            "blocked_reasons": blocked_reason_list,
            "recovery_actions": [],
            "warnings": warning_list,
        }
        assert_json_serializable(result)
        return result

    actions: list[dict[str, Any]] = []
    recovery_actions: list[str] = []
    final_status = "no_action_required"
    final_blocked_reasons = list(blocked_reason_list)

    for index, step in enumerate(step_list):
        step_index = int(step.get("step_index", index))
        tool_name = _safe_string(step, "tool_name")
        detected_issue = step.get("detected_issue")
        if detected_issue is not None:
            detected_issue = str(detected_issue)
        action_type = _safe_string(step, "recommended_action", "continue")
        inspection_step_status = _safe_string(step, "inspection_status", "clear")
        recovery_reason = _safe_string(step, "recovery_reason")
        recovery_plan = (
            to_json_dict(step.get("recovery_plan"))
            if isinstance(step.get("recovery_plan"), Mapping)
            else _default_recovery_plan(action_type, "")
        )
        next_step_hint = _safe_string(recovery_plan, "next_step_hint") or _safe_string(step, "next_step_hint")

        reason = "No failure detected; continue." if action_type == "continue" else ""
        if action_type == "block_next_stage":
            final_status = "blocked"
            reason = "Zero CIFs would block the next stage."
            if not final_blocked_reasons:
                final_blocked_reasons.append("Result inspection blocked the next stage.")
        elif action_type == "recompile_request":
            if final_status != "blocked":
                final_status = "recovery_planned"
            reason = "QLIP infeasible signal requires request recompilation."
            recovery_actions.append(action_type)
            if not next_step_hint:
                next_step_hint = "Revise the QLIP request formulation before solving again."
        elif action_type == "fallback_retrieval":
            if final_status != "blocked":
                final_status = "recovery_planned"
            reason = "No exportable structures signal requires fallback retrieval."
            recovery_actions.append(action_type)
            if not next_step_hint:
                next_step_hint = "Run fallback retrieval or broaden export constraints."
        elif action_type == "skip_optional_stage":
            if final_status != "blocked":
                final_status = "recovery_planned"
            reason = "SPP blocked signal allows skipping an optional stage."
            recovery_actions.append(action_type)
            if not next_step_hint:
                next_step_hint = "Continue only on a path that does not require the blocked optional stage."
        elif action_type == "repackage_qlip_request":
            if final_status != "blocked":
                final_status = "recovery_planned"
            reason = "QLIP packaging or validation diagnostics require rebuilding the request."
            next_step_hint = next_step_hint or "Rebuild QLIP request from SPP bundle with valid pot_root/guidance params before solving."
            recovery_actions.append(action_type)
        elif action_type == "repair_spp_qlip_package":
            if final_status != "blocked":
                final_status = "recovery_planned"
            reason = "SPP did not emit a solve-compatible QLIP request."
            next_step_hint = next_step_hint or "Repair SPP QLIP package compatibility so request_ref is available."
            recovery_actions.append(action_type)
        elif action_type == "revise_qlip_formulation":
            if final_status != "blocked":
                final_status = "recovery_planned"
            reason = "QLIP solve returned a non-solution status."
            next_step_hint = next_step_hint or "Revise the QLIP formulation before retrying solve."
            recovery_actions.append(action_type)
        elif inspection_step_status == "clear":
            action_type = "continue"
            recovery_plan = _default_recovery_plan(action_type, next_step_hint)

        recovery_plan = dict(recovery_plan)
        recovery_plan["action"] = action_type
        recovery_plan["recommended_action"] = action_type
        if next_step_hint:
            recovery_plan["next_step_hint"] = next_step_hint
            recovery_plan["hint"] = next_step_hint

        actions.append(
            {
                "action_index": index,
                "source_step_index": step_index,
                "tool_name": tool_name,
                "detected_issue": detected_issue,
                "action_type": action_type,
                "reason": reason,
                "recovery_reason": recovery_reason,
                "next_step_hint": next_step_hint,
                "recoverable": bool(recovery_plan.get("recoverable", action_type != "continue")),
                "evidence_path": recovery_plan.get("evidence_path"),
                "recovery_plan": recovery_plan,
            }
        )

    result = {
        "schema_version": FAILURE_HANDLING_SCHEMA_VERSION,
        "status": final_status,
        "actions": actions,
        "blocked_reasons": final_blocked_reasons,
        "recovery_actions": recovery_actions,
        "warnings": warning_list,
    }
    assert_json_serializable(result)
    return result


__all__ = [
    "FAILURE_HANDLING_SCHEMA_VERSION",
    "handle_inspection_failures",
]
