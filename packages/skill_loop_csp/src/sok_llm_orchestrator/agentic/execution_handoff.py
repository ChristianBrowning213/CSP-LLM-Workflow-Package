from __future__ import annotations

from typing import Any, Mapping

from .schemas import assert_json_serializable, to_json_dict

EXECUTION_HANDOFF_SCHEMA_VERSION = "agentic_csp.execution_handoff.v1"
DEFAULT_PREFLIGHT_REQUIREMENTS = [
    "executor_available",
    "tool_registry_compatible",
    "operator_allows_execution",
    "workspace_writeable",
]


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    return default


def build_execution_handoff(
    chain_result: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(chain_result, Mapping):
        msg = "chain_result must be a mapping"
        raise TypeError(msg)

    chain_dict = to_json_dict(chain_result)
    execution_intent = chain_dict.get("execution_intent")
    if not isinstance(execution_intent, Mapping):
        execution_intent = {}

    selected_proposals = execution_intent.get("selected_proposals")
    selected_proposal_list = (
        [to_json_dict(item) for item in selected_proposals if isinstance(item, Mapping)]
        if isinstance(selected_proposals, list)
        else []
    )

    execution_allowed = execution_intent.get("execution_allowed") is True
    selected_tool_sequence = (
        [
            str(item.get("tool_name", "")).strip()
            for item in selected_proposal_list
            if str(item.get("tool_name", "")).strip()
        ]
        if execution_allowed
        else []
    )

    blocked_reasons = execution_intent.get("blocked_reasons")
    blocked_reason_list = (
        [str(item) for item in blocked_reasons if str(item).strip()]
        if isinstance(blocked_reasons, list)
        else []
    )

    warnings = execution_intent.get("warnings")
    warning_list = (
        [str(item) for item in warnings if str(item).strip()]
        if isinstance(warnings, list)
        else []
    )

    result = {
        "schema_version": EXECUTION_HANDOFF_SCHEMA_VERSION,
        "status": "ready" if execution_allowed else "blocked",
        "execution_intent_status": _safe_string(execution_intent, "status"),
        "execution_allowed": execution_allowed,
        "selected_tool_sequence": selected_tool_sequence,
        "selected_proposals": selected_proposal_list,
        "preflight_requirements": list(DEFAULT_PREFLIGHT_REQUIREMENTS),
        "blocked_reasons": blocked_reason_list,
        "warnings": warning_list,
        "source_chain_schema_version": _safe_string(chain_dict, "schema_version"),
        "source_run_id": _safe_string(chain_dict, "run_id"),
    }
    assert_json_serializable(result)
    return result


__all__ = [
    "DEFAULT_PREFLIGHT_REQUIREMENTS",
    "EXECUTION_HANDOFF_SCHEMA_VERSION",
    "build_execution_handoff",
]
