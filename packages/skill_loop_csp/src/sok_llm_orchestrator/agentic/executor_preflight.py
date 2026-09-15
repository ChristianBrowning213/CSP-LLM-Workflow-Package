from __future__ import annotations

from typing import Any, Mapping, Sequence

from .schemas import assert_json_serializable, to_json_dict

EXECUTOR_PREFLIGHT_SCHEMA_VERSION = "agentic_csp.executor_preflight.v1"


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    return default


def build_executor_preflight(
    execution_handoff: Mapping[str, Any],
    available_tools: Sequence[str] | None = None,
    operator_allows_execution: bool = False,
    workspace_writeable: bool = False,
) -> dict[str, Any]:
    if not isinstance(execution_handoff, Mapping):
        msg = "execution_handoff must be a mapping"
        raise TypeError(msg)

    handoff_dict = to_json_dict(execution_handoff)
    selected_tool_sequence = handoff_dict.get("selected_tool_sequence")
    selected_proposals = handoff_dict.get("selected_proposals")

    tool_sequence = (
        [str(item).strip() for item in selected_tool_sequence if str(item).strip()]
        if isinstance(selected_tool_sequence, list)
        else []
    )
    proposal_list = (
        [to_json_dict(item) for item in selected_proposals if isinstance(item, Mapping)]
        if isinstance(selected_proposals, list)
        else []
    )

    checked_requirements = [
        "execution_handoff_ready",
        "operator_allows_execution",
        "workspace_writeable",
    ]
    if available_tools is not None:
        checked_requirements.append("tool_registry_compatible")

    missing_requirements: list[str] = []
    blocked_reasons: list[str] = []
    warnings = handoff_dict.get("warnings")
    warning_list = (
        [str(item) for item in warnings if str(item).strip()]
        if isinstance(warnings, list)
        else []
    )

    if _safe_string(handoff_dict, "status") != "ready":
        missing_requirements.append("execution_handoff_ready")
        blocked_reasons.append(
            "Execution handoff is not ready for a future executor."
        )

    if not operator_allows_execution:
        missing_requirements.append("operator_allows_execution")
        blocked_reasons.append("Operator approval for execution is not enabled.")

    if not workspace_writeable:
        missing_requirements.append("workspace_writeable")
        blocked_reasons.append("Workspace is not marked writeable for execution staging.")

    if available_tools is not None:
        available_tool_set = {str(item).strip() for item in available_tools if str(item).strip()}
        if any(tool_name not in available_tool_set for tool_name in tool_sequence):
            missing_requirements.append("tool_registry_compatible")
            blocked_reasons.append(
                "Selected tool sequence is not fully compatible with the available tool registry."
            )

    execution_allowed = not missing_requirements
    result = {
        "schema_version": EXECUTOR_PREFLIGHT_SCHEMA_VERSION,
        "status": "pass" if execution_allowed else "blocked",
        "execution_allowed": execution_allowed,
        "dry_run_only": True,
        "checked_requirements": checked_requirements,
        "missing_requirements": missing_requirements,
        "blocked_reasons": blocked_reasons,
        "selected_tool_sequence": tool_sequence,
        "selected_proposals": proposal_list,
    }
    if warning_list:
        result["warnings"] = warning_list
    else:
        result["warnings"] = []
    assert_json_serializable(result)
    return result


__all__ = [
    "EXECUTOR_PREFLIGHT_SCHEMA_VERSION",
    "build_executor_preflight",
]
