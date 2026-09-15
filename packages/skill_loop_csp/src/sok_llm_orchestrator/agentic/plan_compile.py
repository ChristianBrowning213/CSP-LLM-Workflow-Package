from __future__ import annotations

from typing import Any, Mapping

from .schemas import (
    TOOL_CALL_PROPOSAL_SCHEMA_VERSION,
    ToolCallProposal,
    assert_json_serializable,
    to_json_dict,
)
from .tools import AgenticToolRegistry, default_agentic_tool_registry

PLAN_COMPILE_SCHEMA_VERSION = "agentic_csp.plan_compile.v1"
TOOL_PARSE_REPORT_SCHEMA_VERSION = "agentic_csp.tool_parse_report.v1"


def _safe_string(input_payload: Mapping[str, Any], key: str, default: str = "") -> str:
    value = input_payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return default


def _append_unique(items: list[str], value: str) -> None:
    text = value.strip()
    if text and text not in items:
        items.append(text)


def _tool_hints_from_run_plan(run_plan: Mapping[str, Any]) -> list[str]:
    hints: list[str] = []

    tool_hint_value = run_plan.get("tool_hint")
    if isinstance(tool_hint_value, str):
        _append_unique(hints, tool_hint_value)
    elif isinstance(tool_hint_value, (list, tuple)):
        for item in tool_hint_value:
            if isinstance(item, str):
                _append_unique(hints, item)

    plan_as_text = run_plan.get("plan_as_text")
    if isinstance(plan_as_text, str):
        for line in plan_as_text.splitlines():
            stripped = line.strip()
            lower = stripped.lower()
            for prefix in ("tool_hint:", "tool_hint="):
                if lower.startswith(prefix):
                    _append_unique(hints, stripped[len(prefix) :].strip())
                    break

    return hints


def _proposal_case_id(run_plan: Mapping[str, Any]) -> str:
    return _safe_string(run_plan, "run_id", "run-plan-compile")


def _proposal_objective_family(run_plan: Mapping[str, Any]) -> str:
    return _safe_string(
        run_plan,
        "objective_family",
        _safe_string(run_plan, "overall_goal", "feasibility"),
    )


def _proposal_material_system(run_plan: Mapping[str, Any]) -> str:
    metadata = run_plan.get("metadata")
    if isinstance(metadata, Mapping):
        value = _safe_string(metadata, "material_system")
        if value:
            return value
    return _safe_string(run_plan, "material_system")


def _proposal_for_known_tool_hint(
    tool_name: str,
    run_plan: Mapping[str, Any],
) -> tuple[ToolCallProposal, str | None]:
    case_id = _proposal_case_id(run_plan)
    objective_family = _proposal_objective_family(run_plan)

    if tool_name == "crystal.csp_pack":
        arguments = {
            "case_id": case_id,
            "objective_family": objective_family,
        }
        material_system = _proposal_material_system(run_plan)
        if material_system:
            arguments["material_system"] = material_system
        return (
            ToolCallProposal(
                schema_version=TOOL_CALL_PROPOSAL_SCHEMA_VERSION,
                step="Prepare a future crystal.csp_pack proposal from the current run plan.",
                tool_name=tool_name,
                arguments=arguments,
                expected_result="A proposal-time CSP pack request with no execution performed.",
                why="The run plan explicitly requested crystal.csp_pack through a deterministic tool hint.",
                condition="Review only; no CSP execution has occurred.",
            ),
            None,
        )

    if tool_name == "crystal.novelty_check":
        return (
            ToolCallProposal(
                schema_version=TOOL_CALL_PROPOSAL_SCHEMA_VERSION,
                step="Prepare a future crystal.novelty_check proposal after proposal review.",
                tool_name=tool_name,
                arguments={"case_id": case_id},
                expected_result="A proposal-time novelty-check request with no execution performed.",
                why="The run plan included a novelty-check tool hint in the proposed sequence.",
                condition="Review only; no novelty check has executed.",
            ),
            None,
        )

    placeholder_warning = ""
    if tool_name == "spp.run_pipeline":
        arguments = {
            "case_id": case_id,
            "corpus_ref": "pending_corpus_ref",
        }
        material_system = _proposal_material_system(run_plan)
        if material_system:
            arguments["material_system"] = material_system
        placeholder_warning = (
            "Tool hint spp.run_pipeline uses proposal-time placeholder ref corpus_ref=pending_corpus_ref."
        )
        proposal = ToolCallProposal(
            schema_version=TOOL_CALL_PROPOSAL_SCHEMA_VERSION,
            step="Prepare a future spp.run_pipeline proposal using a pending corpus reference.",
            tool_name=tool_name,
            arguments=arguments,
            expected_result="A proposal-time SPP pipeline request with pending corpus ref and no execution performed.",
            why="The run plan proposed an SPP pipeline step in the future CSP workflow.",
            condition="Review only; corpus_ref is still a pending proposal-time reference.",
        )
        return proposal, placeholder_warning

    if tool_name == "spp.package_for_qlip":
        arguments = {
            "case_id": case_id,
            "spp_package_ref": "pending_spp_package_ref",
        }
        material_system = _proposal_material_system(run_plan)
        if material_system:
            arguments["material_system"] = material_system
        placeholder_warning = (
            "Tool hint spp.package_for_qlip uses proposal-time placeholder ref spp_package_ref=pending_spp_package_ref."
        )
        proposal = ToolCallProposal(
            schema_version=TOOL_CALL_PROPOSAL_SCHEMA_VERSION,
            step="Prepare a future spp.package_for_qlip proposal using a pending SPP package ref.",
            tool_name=tool_name,
            arguments=arguments,
            expected_result="A proposal-time packaging request with pending SPP package ref and no execution performed.",
            why="The run plan proposed packaging SPP outputs for a later QLIP request.",
            condition="Review only; spp_package_ref is still a pending proposal-time reference.",
        )
        return proposal, placeholder_warning

    if tool_name == "qlip.validate_request":
        placeholder_warning = (
            "Tool hint qlip.validate_request uses proposal-time placeholder ref request_ref=pending_request_ref."
        )
        proposal = ToolCallProposal(
            schema_version=TOOL_CALL_PROPOSAL_SCHEMA_VERSION,
            step="Prepare a future qlip.validate_request proposal using a pending request ref.",
            tool_name=tool_name,
            arguments={
                "case_id": case_id,
                "request_ref": "pending_request_ref",
            },
            expected_result="A proposal-time validation request with pending request ref and no execution performed.",
            why="The run plan proposed a QLIP validation step in the future workflow.",
            condition="Review only; request_ref is still a pending proposal-time reference.",
        )
        return proposal, placeholder_warning

    if tool_name == "qlip.solve":
        placeholder_warning = (
            "Tool hint qlip.solve uses proposal-time placeholder ref validated_request_ref=pending_validated_request_ref."
        )
        proposal = ToolCallProposal(
            schema_version=TOOL_CALL_PROPOSAL_SCHEMA_VERSION,
            step="Prepare a future qlip.solve proposal using a pending validated request ref.",
            tool_name=tool_name,
            arguments={
                "case_id": case_id,
                "validated_request_ref": "pending_validated_request_ref",
            },
            expected_result="A proposal-time solve request with pending validated request ref and no execution performed.",
            why="The run plan proposed a QLIP solve step in the future workflow.",
            condition="Review only; validated_request_ref is still a pending proposal-time reference.",
        )
        return proposal, placeholder_warning

    msg = f"Known tool handling missing for: {tool_name}"
    raise ValueError(msg)


def _unknown_tool_validation_result(
    tool_name: str,
    registry: AgenticToolRegistry,
) -> dict[str, Any]:
    placeholder = ToolCallProposal(
        schema_version=TOOL_CALL_PROPOSAL_SCHEMA_VERSION,
        step="Record an unknown tool hint without execution.",
        tool_name=tool_name,
        arguments={},
        expected_result="No execution occurs because the tool hint is unknown.",
        why="The run plan referenced a tool that is not present in the agentic registry.",
        condition="Do not execute unknown tool hints.",
    )
    return registry.validate_tool_call_proposal(to_json_dict(placeholder))


def compile_run_plan_to_tool_proposals(
    run_plan: Mapping[str, Any],
    registry: AgenticToolRegistry | None = None,
) -> dict[str, Any]:
    if not isinstance(run_plan, Mapping):
        msg = "run_plan must be a mapping"
        raise TypeError(msg)

    active_registry = registry or default_agentic_tool_registry()
    proposals: list[dict[str, Any]] = []
    validation_results: list[dict[str, Any]] = []
    warnings: list[str] = []

    for tool_hint in _tool_hints_from_run_plan(run_plan):
        if not active_registry.has_tool(tool_hint):
            warnings.append(f"Unknown tool_hint: {tool_hint}")
            validation_results.append(_unknown_tool_validation_result(tool_hint, active_registry))
            continue

        proposal, warning = _proposal_for_known_tool_hint(tool_hint, run_plan)
        proposal_dict = to_json_dict(proposal)
        validation_result = active_registry.validate_tool_call_proposal(proposal_dict)

        proposals.append(proposal_dict)
        validation_results.append(validation_result)
        if warning:
            warnings.append(warning)

    result = {
        "schema_version": PLAN_COMPILE_SCHEMA_VERSION,
        "proposals": proposals,
        "validation_results": validation_results,
        "warnings": warnings,
    }
    assert_json_serializable(result)
    return result


def build_tool_parse_report(
    compile_result: Mapping[str, Any],
    route_mode: str | None = None,
) -> dict[str, Any]:
    if not isinstance(compile_result, Mapping):
        msg = "compile_result must be a mapping"
        raise TypeError(msg)

    compile_dict = to_json_dict(compile_result)
    proposals = (
        [to_json_dict(item) for item in compile_dict.get("proposals", []) if isinstance(item, Mapping)]
        if isinstance(compile_dict.get("proposals"), list)
        else []
    )
    validation_results = (
        [to_json_dict(item) for item in compile_dict.get("validation_results", []) if isinstance(item, Mapping)]
        if isinstance(compile_dict.get("validation_results"), list)
        else []
    )
    warning_list = (
        [str(item) for item in compile_dict.get("warnings", []) if str(item).strip()]
        if isinstance(compile_dict.get("warnings"), list)
        else []
    )
    valid_count = sum(1 for item in validation_results if item.get("valid") is True)
    invalid_count = sum(1 for item in validation_results if item.get("valid") is False)

    result = {
        "schema_version": TOOL_PARSE_REPORT_SCHEMA_VERSION,
        "proposal_count": len(proposals),
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "tool_sequence": [
            _safe_string(item, "tool_name") for item in proposals if _safe_string(item, "tool_name")
        ],
        "warnings": warning_list,
    }
    if isinstance(route_mode, str) and route_mode.strip():
        result["route_mode"] = route_mode
    assert_json_serializable(result)
    return result


__all__ = [
    "PLAN_COMPILE_SCHEMA_VERSION",
    "TOOL_PARSE_REPORT_SCHEMA_VERSION",
    "build_tool_parse_report",
    "compile_run_plan_to_tool_proposals",
]
