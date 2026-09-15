from __future__ import annotations

import json
from typing import Any, Mapping

from .schemas import assert_json_serializable, to_json_dict

RESULT_INSPECTION_SCHEMA_VERSION = "agentic_csp.result_inspection.v1"


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    return default


def _mapping_list(mapping: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = mapping.get(key)
    if not isinstance(value, list):
        return []
    return [to_json_dict(item) for item in value if isinstance(item, Mapping)]


def _artifact_ref(step_result: Mapping[str, Any], ref_name: str) -> str:
    for item in _mapping_list(step_result, "artifact_refs"):
        if _safe_string(item, "ref_name") == ref_name:
            return _safe_string(item, "value")
    return ""


def _latest_prior(prior_steps: list[Mapping[str, Any]], tool_name: str) -> dict[str, Any] | None:
    for step in reversed(prior_steps):
        if _safe_string(step, "tool_name") == tool_name:
            return to_json_dict(step)
    return None


def _recovery_plan(
    issue: str | None,
    action: str,
    hint: str,
    *,
    evidence_path: str = "",
    recoverable: bool = True,
    requires_new_data: bool = False,
    requires_formulation_change: bool = False,
) -> dict[str, Any]:
    return {
        "recovery_recommended": bool(issue and action != "continue"),
        "action": action,
        "can_auto_retry": False,
        "requires_new_data": bool(requires_new_data),
        "requires_formulation_change": bool(requires_formulation_change),
        "recoverable": bool(recoverable),
        "recommended_action": action,
        "next_step_hint": hint,
        "hint": hint,
        "evidence_path": evidence_path or None,
    }


def _classify_non_solution_status(status: str, errors: list[dict[str, Any]]) -> tuple[str, str, bool, bool]:
    upper = status.upper()
    error_codes = {_safe_string(item, "code") for item in errors}
    if upper == "INFEASIBLE":
        return (
            "qlip_infeasible",
            "Revise the QLIP formulation: reduce constraints, enlarge the candidate site space, or relax lattice/site requirements.",
            False,
            True,
        )
    if "unit_cell_missing" in error_codes:
        return ("qlip_unit_cell_missing", "Add a lattice template/unit cell before solving.", False, True)
    if "lattice_bounds_invalid" in error_codes:
        return ("qlip_lattice_bounds_invalid", "Correct invalid lattice bounds before solving.", False, True)
    if "assignment_space_empty" in error_codes or "candidate_sites_empty" in error_codes:
        return ("qlip_site_space_infeasible", "Increase or repair candidate sites before solving.", False, True)
    if upper == "ERROR":
        return (
            "qlip_error",
            "Revise the QLIP formulation: inspect QLIP solve diagnostics and repair the request or runtime data before retrying.",
            False,
            True,
        )
    return (
        "qlip_non_solution_status",
        f"QLIP returned non-solution status {status}; inspect solve diagnostics before retrying.",
        False,
        True,
    )


def _solve_warning_errors(step_result: Mapping[str, Any]) -> list[dict[str, Any]]:
    parsed_errors: list[dict[str, Any]] = []
    warnings = step_result.get("warnings")
    if not isinstance(warnings, list):
        return parsed_errors
    for warning in warnings:
        if not isinstance(warning, str):
            continue
        try:
            payload = json.loads(warning)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, Mapping):
            continue
        errors = payload.get("errors")
        if isinstance(errors, list):
            parsed_errors.extend(to_json_dict(item) for item in errors if isinstance(item, Mapping))
    return parsed_errors


def _detect_issue(
    step_result: Mapping[str, Any],
    prior_steps: list[Mapping[str, Any]],
) -> tuple[str, str, str | None, str, dict[str, Any]] | None:
    tool_name = _safe_string(step_result, "tool_name")
    result_summary = _safe_string(step_result, "result_summary").lower()
    metadata = step_result.get("metadata")
    metadata_dict = to_json_dict(metadata) if isinstance(metadata, Mapping) else {}
    output_summary = (
        to_json_dict(step_result.get("output_summary"))
        if isinstance(step_result.get("output_summary"), Mapping)
        else {}
    )
    error = (
        to_json_dict(step_result.get("error"))
        if isinstance(step_result.get("error"), Mapping)
        else {}
    )

    cif_count = metadata_dict.get("cif_count")
    evidence_path = _safe_string(step_result, "raw_result_ref")
    if cif_count == 0 or "cif_count: 0" in result_summary or "zero_cifs" in result_summary:
        hint = "Fix retrieval/export so crystal.csp_pack produces at least one exportable CIF."
        return ("zero_cifs", "block_next_stage", None, hint, _recovery_plan("zero_cifs", "block_next_stage", hint, evidence_path=evidence_path, requires_new_data=True))
    if metadata_dict.get("qlip_infeasible") is True or "qlip_infeasible" in result_summary:
        hint = "Revise the QLIP request formulation before solving again."
        return ("qlip_infeasible", "recompile_request", None, hint, _recovery_plan("qlip_infeasible", "recompile_request", hint, evidence_path=evidence_path, requires_formulation_change=True))
    if metadata_dict.get("no_exportable_structures") is True or "no_exportable_structures" in result_summary:
        hint = "Run fallback retrieval or broaden export constraints."
        return ("no_exportable_structures", "fallback_retrieval", None, hint, _recovery_plan("no_exportable_structures", "fallback_retrieval", hint, evidence_path=evidence_path, requires_new_data=True))
    if metadata_dict.get("spp_blocked") is True or "spp_blocked" in result_summary:
        hint = "Treat SPP as blocked and continue only on a path that does not require SPP guidance."
        return ("spp_blocked", "skip_optional_stage", None, hint, _recovery_plan("spp_blocked", "skip_optional_stage", hint, evidence_path=evidence_path))

    qlip_packaging_codes = {
        "qlip_package_invalid",
        "qlip_request_packaging_invalid",
        "pot_root_missing",
        "invalid_guidance_params",
        "qlip_request_invalid",
    }
    validation_errors = _mapping_list(output_summary, "validation_errors")
    validation_error_codes = {
        _safe_string(item, "code")
        for item in validation_errors
        if _safe_string(item, "code")
    }
    error_code = _safe_string(error, "code")
    if error_code == "unresolved_placeholder_ref" and tool_name == "qlip.validate_request":
        prior_spp = _latest_prior(prior_steps, "spp.run_pipeline")
        if isinstance(prior_spp, Mapping):
            spp_summary = prior_spp.get("output_summary") if isinstance(prior_spp.get("output_summary"), Mapping) else {}
            if spp_summary.get("request_ref") in {None, ""} or spp_summary.get("qlip_solve_compatible") is False:
                missing_pairs = spp_summary.get("qlip_package_missing_pairs")
                missing_text = ", ".join(str(item) for item in missing_pairs) if isinstance(missing_pairs, list) else ""
                hint = "Repair SPP package compatibility so it emits request_ref before qlip.validate_request."
                if missing_text:
                    hint = f"Add/choose POT coverage for missing pairs ({missing_text}) so SPP emits a solve-compatible request_ref."
                evidence = _safe_string(prior_spp, "raw_result_ref") or _artifact_ref(prior_spp, "spp_qlip_package_json")
                return (
                    "spp_request_ref_unavailable",
                    "repair_spp_qlip_package",
                    "spp_no_request_ref",
                    hint,
                    _recovery_plan(
                        "spp_request_ref_unavailable",
                        "repair_spp_qlip_package",
                        hint,
                        evidence_path=evidence,
                        requires_new_data=True,
                    ),
                )
    if error_code == "spp_request_ref_unavailable":
        hint = _safe_string(error, "message", "Repair SPP QLIP package compatibility so request_ref is available.")
        return (
            "spp_request_ref_unavailable",
            "repair_spp_qlip_package",
            "spp_no_request_ref",
            hint,
            _recovery_plan("spp_request_ref_unavailable", "repair_spp_qlip_package", hint, evidence_path=evidence_path, requires_new_data=True),
        )
    if tool_name == "qlip.validate_request" and output_summary.get("valid") is False:
        issue_code = next(
            (
                code
                for code in (
                    "pot_root_missing",
                    "invalid_guidance_params",
                    "qlip_request_invalid",
                )
                if code in validation_error_codes
            ),
            "qlip_request_invalid",
        )
        hint = "Rebuild QLIP request from SPP bundle with valid pot_root/guidance params before solving."
        return (
            issue_code,
            "repackage_qlip_request",
            "missing_or_invalid_qlip_packaging_inputs",
            hint,
            _recovery_plan(issue_code, "repackage_qlip_request", hint, evidence_path=evidence_path, requires_formulation_change=True),
        )
    if error_code in qlip_packaging_codes:
        hint = "Rebuild QLIP request from SPP bundle with valid pot_root/guidance params before solving."
        return (
            error_code,
            "repackage_qlip_request",
            "missing_or_invalid_qlip_packaging_inputs",
            hint,
            _recovery_plan(error_code, "repackage_qlip_request", hint, evidence_path=evidence_path, requires_formulation_change=True),
        )
    if tool_name == "qlip.solve" and error_code == "non_solution_status":
        qlip_status = _safe_string(step_result.get("raw_result_summary", {}) if isinstance(step_result.get("raw_result_summary"), Mapping) else {}, "status")
        errors = _mapping_list(output_summary, "errors") or _solve_warning_errors(step_result)
        issue_code, hint, requires_new_data, requires_formulation_change = _classify_non_solution_status(qlip_status, errors)
        return (
            issue_code,
            "revise_qlip_formulation",
            "qlip_solve_non_solution_status",
            hint,
            _recovery_plan(
                issue_code,
                "revise_qlip_formulation",
                hint,
                evidence_path=evidence_path,
                requires_new_data=requires_new_data,
                requires_formulation_change=requires_formulation_change,
            ),
        )
    if tool_name == "qlip.solve" and error_code in {"qlip_error", "qlip_infeasible", "qlip_non_solution_status"}:
        issue_code = error_code
        hint = "Inspect QLIP solve diagnostics and revise the formulation before retrying."
        if error_code == "qlip_infeasible":
            hint = "Revise QLIP constraints, lattice, or candidate site space before retrying."
        return (
            issue_code,
            "revise_qlip_formulation",
            "qlip_solve_non_solution_status",
            hint,
            _recovery_plan(issue_code, "revise_qlip_formulation", hint, evidence_path=evidence_path, requires_formulation_change=True),
        )
    return None


def inspect_step_results(
    noop_step_execution: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(noop_step_execution, Mapping):
        msg = "noop_step_execution must be a mapping"
        raise TypeError(msg)

    execution_dict = to_json_dict(noop_step_execution)
    warnings = execution_dict.get("warnings")
    warning_list = (
        [str(item) for item in warnings if str(item).strip()]
        if isinstance(warnings, list)
        else []
    )
    blocked_reasons = execution_dict.get("blocked_reasons")
    blocked_reason_list = (
        [str(item) for item in blocked_reasons if str(item).strip()]
        if isinstance(blocked_reasons, list)
        else []
    )

    if _safe_string(execution_dict, "status") == "blocked":
        result = {
            "schema_version": RESULT_INSPECTION_SCHEMA_VERSION,
            "status": "blocked",
            "inspected_steps": [],
            "blocked_reasons": blocked_reason_list,
            "recovery_recommendations": [],
            "warnings": warning_list,
        }
        assert_json_serializable(result)
        return result

    step_results = execution_dict.get("step_results")
    step_list = (
        [to_json_dict(item) for item in step_results if isinstance(item, Mapping)]
        if isinstance(step_results, list)
        else []
    )
    inspected_steps: list[dict[str, Any]] = []
    overall_status = "clear"
    recovery_recommendations: list[str] = []
    result_blocked_reasons: list[str] = []

    for index, step in enumerate(step_list):
        input_status = _safe_string(step, "status")
        inspection_status = "clear"
        detected_issue: str | None = None
        recommended_action = "continue"
        recovery_reason: str | None = None
        next_step_hint = ""
        recovery_plan = _recovery_plan(None, "continue", "", recoverable=True)

        issue = _detect_issue(step, step_list[:index])
        if issue is not None:
            detected_issue, recommended_action, recovery_reason, next_step_hint, recovery_plan = issue
            if recommended_action == "block_next_stage":
                inspection_status = "blocked"
                overall_status = "blocked"
                result_blocked_reasons.append(
                    f"Step {_safe_string(step, 'tool_name', str(index))} detected zero CIFs."
                )
            else:
                inspection_status = "recovery_recommended"
                if overall_status != "blocked":
                    overall_status = "recovery_recommended"
                recommendation_text = (
                    f"{_safe_string(step, 'tool_name', str(index))}: {recommended_action}"
                )
                if recommendation_text not in recovery_recommendations:
                    recovery_recommendations.append(recommendation_text)

        inspected_steps.append(
            {
                "step_index": int(step.get("step_index", index)),
                "tool_name": _safe_string(step, "tool_name"),
                "input_status": input_status,
                "inspection_status": inspection_status,
                "detected_issue": detected_issue,
                "recommended_action": recommended_action,
                "recovery_reason": recovery_reason,
                "recoverable": bool(recovery_plan.get("recoverable", True)),
                "next_step_hint": next_step_hint,
                "evidence_path": recovery_plan.get("evidence_path"),
                "recovery_plan": recovery_plan,
            }
        )

    result = {
        "schema_version": RESULT_INSPECTION_SCHEMA_VERSION,
        "status": overall_status,
        "inspected_steps": inspected_steps,
        "blocked_reasons": result_blocked_reasons,
        "recovery_recommendations": recovery_recommendations,
        "warnings": warning_list,
    }
    assert_json_serializable(result)
    return result


__all__ = [
    "RESULT_INSPECTION_SCHEMA_VERSION",
    "inspect_step_results",
]
