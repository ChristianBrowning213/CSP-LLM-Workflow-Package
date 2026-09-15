from __future__ import annotations

from typing import Any, Mapping

from .schemas import assert_json_serializable, to_json_dict

NOOP_EXECUTION_REPORT_SCHEMA_VERSION = "agentic_csp.noop_execution_report.v1"


def build_noop_execution_report(
    executor_preflight: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(executor_preflight, Mapping):
        msg = "executor_preflight must be a mapping"
        raise TypeError(msg)

    preflight_dict = to_json_dict(executor_preflight)
    selected_tool_sequence = preflight_dict.get("selected_tool_sequence")
    selected_proposals = preflight_dict.get("selected_proposals")
    blocked_reasons = preflight_dict.get("blocked_reasons")
    warnings = preflight_dict.get("warnings")

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
    blocked_reason_list = (
        [str(item) for item in blocked_reasons if str(item).strip()]
        if isinstance(blocked_reasons, list)
        else []
    )
    warning_list = (
        [str(item) for item in warnings if str(item).strip()]
        if isinstance(warnings, list)
        else []
    )

    preflight_passed = (
        preflight_dict.get("status") == "pass"
        and preflight_dict.get("execution_allowed") is True
    )
    result = {
        "schema_version": NOOP_EXECUTION_REPORT_SCHEMA_VERSION,
        "mode": "noop_dry_run",
        "status": "would_execute" if preflight_passed else "blocked",
        "execution_performed": False,
        "selected_tool_sequence": tool_sequence,
        "selected_proposals": proposal_list,
        "would_call_tools": tool_sequence if preflight_passed else [],
        "blocked_reasons": [] if preflight_passed else blocked_reason_list,
        "warnings": warning_list,
        "dry_run_only": True,
    }
    assert_json_serializable(result)
    return result


__all__ = [
    "NOOP_EXECUTION_REPORT_SCHEMA_VERSION",
    "build_noop_execution_report",
]
