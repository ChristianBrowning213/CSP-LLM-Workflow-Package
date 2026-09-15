from __future__ import annotations

from typing import Any, Mapping

from .schemas import assert_json_serializable, to_json_dict

EXECUTION_INTENT_SCHEMA_VERSION = "agentic_csp.execution_intent.v1"


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    return default


def build_execution_intent(
    planner_compile_result: Mapping[str, Any],
    run_manager_log: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(planner_compile_result, Mapping):
        msg = "planner_compile_result must be a mapping"
        raise TypeError(msg)
    if not isinstance(run_manager_log, Mapping):
        msg = "run_manager_log must be a mapping"
        raise TypeError(msg)

    compile_result = planner_compile_result.get("compile_result")
    if not isinstance(compile_result, Mapping):
        compile_result = {}

    proposals = compile_result.get("proposals")
    validation_results = compile_result.get("validation_results")
    compile_warnings = compile_result.get("warnings")

    proposal_list = [to_json_dict(item) for item in proposals if isinstance(item, Mapping)] if isinstance(proposals, list) else []
    validation_list = [to_json_dict(item) for item in validation_results if isinstance(item, Mapping)] if isinstance(validation_results, list) else []

    validation_by_tool_name: dict[str, dict[str, Any]] = {}
    invalid_tool_names: list[str] = []
    warning_messages: list[str] = []
    invalid_messages: list[str] = []

    for item in validation_list:
        tool_name = _safe_string(item, "tool_name", "unknown.tool")
        validation_by_tool_name[tool_name] = item

        item_warnings = item.get("warnings")
        if isinstance(item_warnings, list):
            for warning in item_warnings:
                text = str(warning).strip()
                if text and text not in warning_messages:
                    warning_messages.append(text)

        if item.get("valid") is not True:
            if tool_name not in invalid_tool_names:
                invalid_tool_names.append(tool_name)
            item_errors = item.get("errors")
            if isinstance(item_errors, list):
                for error in item_errors:
                    text = str(error).strip()
                    if text and text not in invalid_messages:
                        invalid_messages.append(text)

    if isinstance(compile_warnings, list):
        for warning in compile_warnings:
            text = str(warning).strip()
            if text and text not in warning_messages:
                warning_messages.append(text)

    selected_proposals: list[dict[str, Any]] = []
    for proposal in proposal_list:
        tool_name = _safe_string(proposal, "tool_name", "unknown.tool")
        validation = validation_by_tool_name.get(tool_name)
        if isinstance(validation, Mapping) and validation.get("valid") is True:
            selected_proposals.append(proposal)

    blocked_reasons: list[str] = []
    manager_notes = _safe_string(run_manager_log, "manager_notes")

    if invalid_tool_names:
        blocked_reasons.append(
            "Invalid tool proposals block execution: " + ", ".join(invalid_tool_names)
        )
        if invalid_messages:
            blocked_reasons.extend(invalid_messages)
        status = "blocked_invalid_proposals"
        execution_allowed = False
    elif not proposal_list:
        blocked_reasons.append("No tool proposals are available for execution review.")
        status = "blocked_no_proposals"
        execution_allowed = False
    elif warning_messages:
        blocked_reasons.append("Proposal warnings require manual review before execution.")
        status = "review_required"
        execution_allowed = False
    else:
        status = "ready_for_execution"
        execution_allowed = True

    if manager_notes and manager_notes not in blocked_reasons and not execution_allowed:
        blocked_reasons.append(manager_notes)

    result = {
        "schema_version": EXECUTION_INTENT_SCHEMA_VERSION,
        "status": status,
        "selected_proposals": selected_proposals,
        "blocked_reasons": blocked_reasons,
        "warnings": warning_messages,
        "execution_allowed": execution_allowed,
    }
    assert_json_serializable(result)
    return result


__all__ = [
    "EXECUTION_INTENT_SCHEMA_VERSION",
    "build_execution_intent",
]
