from __future__ import annotations

from typing import Any, Mapping

from .schemas import assert_json_serializable, to_json_dict

EXECUTABLE_PLAN_SCHEMA_VERSION = "agentic_csp.executable_plan.v1"
EXECUTABLE_PLAN_REPORT_SCHEMA_VERSION = "agentic_csp.executable_plan_report.v1"


def _mapping_list(payload: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [to_json_dict(item) for item in value if isinstance(item, Mapping)]


def _string_list(payload: Mapping[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _placeholder_ref_names(arguments: Mapping[str, Any]) -> list[str]:
    placeholders: list[str] = []
    for key, value in arguments.items():
        if isinstance(value, str) and value.startswith("pending_"):
            placeholders.append(str(key))
    return placeholders


def build_executable_plan_from_compile_result(
    compile_result: Mapping[str, Any],
    *,
    execution_mode: str = "dry_run",
    require_all_valid: bool = True,
) -> dict[str, Any]:
    if not isinstance(compile_result, Mapping):
        msg = "compile_result must be a mapping"
        raise TypeError(msg)

    compile_dict = to_json_dict(compile_result)
    proposals = _mapping_list(compile_dict, "proposals")
    validation_results = _mapping_list(compile_dict, "validation_results")
    warnings = _string_list(compile_dict, "warnings")
    tool_sequence = [
        str(item.get("tool_name"))
        for item in proposals
        if isinstance(item.get("tool_name"), str) and str(item.get("tool_name")).strip()
    ]

    blocked_reasons: list[str] = []
    if not proposals:
        status = "blocked_no_proposals"
        blocked_reasons.append("No validated tool proposals were available to adapt into a dry-run executable plan.")
    elif require_all_valid and any(item.get("valid") is False for item in validation_results):
        status = "blocked_invalid_proposals"
        blocked_reasons.append("One or more tool proposals failed validation, so the dry-run executable plan is blocked.")
    else:
        status = "ready_for_dry_run"

    executable_steps: list[dict[str, Any]] = []
    if status == "ready_for_dry_run":
        for step_index, proposal in enumerate(proposals):
            arguments = to_json_dict(proposal.get("arguments", {}))
            executable_steps.append(
                {
                    "step_index": step_index,
                    "tool_name": proposal.get("tool_name"),
                    "proposal": proposal,
                    "arguments": arguments,
                    "execution_mode": execution_mode,
                    "execution_allowed": False,
                    "status": "pending_dry_run",
                    "audit": {
                        "proposal_schema_version": proposal.get("schema_version"),
                        "source": "compile_result",
                        "placeholder_refs": _placeholder_ref_names(arguments),
                    },
                }
            )

    result = {
        "schema_version": EXECUTABLE_PLAN_SCHEMA_VERSION,
        "execution_mode": execution_mode,
        "execution_allowed": False,
        "status": status,
        "tool_sequence": tool_sequence,
        "executable_steps": executable_steps,
        "blocked_reasons": blocked_reasons,
        "warnings": warnings,
    }
    assert_json_serializable(result)
    return result


def build_executable_plan_report(executable_plan: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(executable_plan, Mapping):
        msg = "executable_plan must be a mapping"
        raise TypeError(msg)

    plan_dict = to_json_dict(executable_plan)
    executable_steps = _mapping_list(plan_dict, "executable_steps")
    warnings = _string_list(plan_dict, "warnings")
    placeholder_ref_count = sum(
        len(
            [
                item
                for item in step.get("audit", {}).get("placeholder_refs", [])
                if isinstance(item, str) and item.strip()
            ]
        )
        for step in executable_steps
        if isinstance(step.get("audit"), Mapping)
    )

    status = str(plan_dict.get("status", ""))
    step_count = len(executable_steps)
    tool_sequence = [
        str(item)
        for item in plan_dict.get("tool_sequence", [])
        if isinstance(item, str) and item.strip()
    ]

    summary = {
        "ready_for_dry_run": f"Executable dry-run plan is ready with {step_count} pending steps.",
        "blocked_invalid_proposals": "Executable dry-run plan is blocked because one or more proposals are invalid.",
        "blocked_no_proposals": "Executable dry-run plan is blocked because no proposals were available.",
    }.get(status, f"Executable dry-run plan is in state: {status or 'unknown'}.")

    result = {
        "schema_version": EXECUTABLE_PLAN_REPORT_SCHEMA_VERSION,
        "status": status,
        "execution_mode": plan_dict.get("execution_mode"),
        "execution_allowed": plan_dict.get("execution_allowed"),
        "step_count": step_count,
        "tool_sequence": tool_sequence,
        "placeholder_ref_count": placeholder_ref_count,
        "warnings": warnings,
        "summary": summary,
    }
    assert_json_serializable(result)
    return result


__all__ = [
    "EXECUTABLE_PLAN_SCHEMA_VERSION",
    "EXECUTABLE_PLAN_REPORT_SCHEMA_VERSION",
    "build_executable_plan_from_compile_result",
    "build_executable_plan_report",
]
