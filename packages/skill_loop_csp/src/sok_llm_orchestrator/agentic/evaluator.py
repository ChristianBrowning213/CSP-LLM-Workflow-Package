from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping

from .schemas import assert_json_serializable, to_json_dict

WORKFLOW_EVALUATION_SCHEMA_VERSION = "agentic_csp.workflow_evaluation.v1"
WORKFLOW_EVALUATION_WRITE_SCHEMA_VERSION = "agentic_csp.workflow_evaluation_write.v1"


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return default


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


def _read_json(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    candidate = Path(path)
    if not candidate.exists():
        return None
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return to_json_dict(payload) if isinstance(payload, Mapping) else None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _latest_step(report: Mapping[str, Any], tool_name: str) -> dict[str, Any] | None:
    for row in reversed(_mapping_list(report, "tool_execution_log")):
        if _safe_string(row, "tool_name") == tool_name:
            return row
    return None


def _failed_or_blocked_step(report: Mapping[str, Any]) -> dict[str, Any] | None:
    for row in _mapping_list(report, "tool_execution_log"):
        if _safe_string(row, "status") in {"failed", "blocked"}:
            return row
    return None


def _first_recovery_action(report: Mapping[str, Any]) -> dict[str, Any] | None:
    notes = report.get("result_continuation_notes") if isinstance(report.get("result_continuation_notes"), Mapping) else {}
    failure = notes.get("failure_handling") if isinstance(notes.get("failure_handling"), Mapping) else {}
    for action in _mapping_list(failure, "actions"):
        if _safe_string(action, "action_type") != "continue":
            return action
    return None


def _canonical_recovery_hint(classification: str) -> str:
    if classification == "qlip_infeasible":
        return "Revise the QLIP formulation: reduce constraints, enlarge the candidate site space, or relax lattice/site requirements."
    if classification in {"qlip_error", "qlip_non_solution_status"}:
        return "Revise the QLIP formulation: inspect QLIP solve diagnostics and repair the request or runtime data before retrying."
    return ""


def _artifact_ref(step: Mapping[str, Any] | None, name: str) -> str:
    if not isinstance(step, Mapping):
        return ""
    for ref in _mapping_list(step, "artifact_refs"):
        if _safe_string(ref, "ref_name") == name:
            return _safe_string(ref, "value")
    return ""


def _artifact_path(report: Mapping[str, Any], label: str) -> str:
    for item in _mapping_list(report, "artifact_index"):
        if _safe_string(item, "label") == label:
            return _safe_string(item, "path")
    return ""


def _path_exists(path: str | None) -> bool:
    return bool(path) and Path(str(path)).exists()


def _status_for_pass_unknown_fail(pass_value: bool | None) -> str:
    if pass_value is True:
        return "pass"
    if pass_value is False:
        return "fail"
    return "unknown"


def _normalize_formula(formula: str | None) -> dict[str, int] | None:
    if not isinstance(formula, str) or not formula.strip():
        return None
    counts: dict[str, int] = {}
    for element, amount in re.findall(r"([A-Z][a-z]?)(\d*)", formula.strip()):
        counts[element] = counts.get(element, 0) + (int(amount) if amount else 1)
    return counts or None


def _formula_from_qlip_payload(payload: Mapping[str, Any] | None) -> str:
    if not isinstance(payload, Mapping):
        return ""
    problem = payload.get("problem")
    if isinstance(problem, Mapping):
        chemistry = problem.get("chemistry")
        if isinstance(chemistry, Mapping):
            formula = _safe_string(chemistry, "formula")
            if formula:
                return formula
    chemistry = payload.get("chemistry")
    if isinstance(chemistry, Mapping):
        return _safe_string(chemistry, "formula")
    return ""


def _formula_from_cif(path: str | None) -> str:
    if not path or not Path(path).exists():
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("_chemical_formula_sum"):
            value = stripped.removeprefix("_chemical_formula_sum").strip().strip("'\"")
            return value.replace(" ", "")
    atom_types: list[str] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and not parts[0].startswith("_") and re.match(r"^[A-Z][a-z]?$", parts[1]):
            atom_types.append(parts[1])
    if atom_types:
        counts: dict[str, int] = {}
        for element in atom_types:
            counts[element] = counts.get(element, 0) + 1
        return "".join(f"{element}{counts[element] if counts[element] != 1 else ''}" for element in sorted(counts))
    return ""


def _score_from_status(status: str, pass_score: int = 100, unknown_score: int = 0) -> int:
    if status == "pass":
        return pass_score
    if status == "unknown":
        return unknown_score
    return 0


def _bounded(value: float | int | None) -> int | None:
    if value is None:
        return None
    return max(0, min(100, int(round(float(value)))))


def load_demo_artifacts_for_evaluation(bundle_or_run_dir: str | Path) -> dict[str, Any]:
    root = Path(bundle_or_run_dir)
    candidates = [
        root / "report" / "execution_loop_report.json",
        root / "_raw_run" / "report" / "execution_loop_report.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return {"execution_loop_report": _read_json(candidate) or {}, "execution_loop_report_path": str(candidate)}
    return {"execution_loop_report": {}, "execution_loop_report_path": ""}


def build_workflow_evaluation(
    execution_loop_report: Mapping[str, Any],
    *,
    execution_loop_report_path: str | Path | None = None,
) -> dict[str, Any]:
    report = to_json_dict(execution_loop_report)
    planner_reply = report.get("llm_planner_reply") if isinstance(report.get("llm_planner_reply"), Mapping) else {}
    run_plan = planner_reply.get("run_plan") if isinstance(planner_reply.get("run_plan"), Mapping) else {}
    plan_source = report.get("plan_source") if isinstance(report.get("plan_source"), Mapping) else {}
    final_outputs = report.get("final_outputs") if isinstance(report.get("final_outputs"), Mapping) else {}
    demo_summary = report.get("demo_summary") if isinstance(report.get("demo_summary"), Mapping) else {}

    run_id = _safe_string(demo_summary, "run_id") or _safe_string(run_plan, "run_id")
    goal = _safe_string(run_plan, "overall_goal") or _safe_string(run_plan, "run_goal")
    material_system = _safe_string(plan_source, "material_system") or _safe_string(demo_summary, "material_or_example")
    backend = _safe_string(plan_source, "mcp_backend") or _safe_string(demo_summary, "backend")
    plan_source_name = _safe_string(plan_source, "plan_source") or _safe_string(demo_summary, "plan_source")

    csp_step = _latest_step(report, "crystal.csp_pack")
    spp_step = _latest_step(report, "spp.run_pipeline")
    package_step = _latest_step(report, "spp.package_for_qlip")
    validate_step = _latest_step(report, "qlip.validate_request")
    solve_step = _latest_step(report, "qlip.solve")
    novelty_step = _latest_step(report, "crystal.novelty_check")

    csp_summary = csp_step.get("output_summary", {}) if isinstance(csp_step, Mapping) and isinstance(csp_step.get("output_summary"), Mapping) else {}
    spp_summary = spp_step.get("output_summary", {}) if isinstance(spp_step, Mapping) and isinstance(spp_step.get("output_summary"), Mapping) else {}
    package_summary = package_step.get("output_summary", {}) if isinstance(package_step, Mapping) and isinstance(package_step.get("output_summary"), Mapping) else {}
    validate_summary = validate_step.get("output_summary", {}) if isinstance(validate_step, Mapping) and isinstance(validate_step.get("output_summary"), Mapping) else {}
    solve_summary = solve_step.get("output_summary", {}) if isinstance(solve_step, Mapping) and isinstance(solve_step.get("output_summary"), Mapping) else {}
    novelty_summary = novelty_step.get("output_summary", {}) if isinstance(novelty_step, Mapping) and isinstance(novelty_step.get("output_summary"), Mapping) else {}

    request_ref = _safe_string(final_outputs, "request_ref") or _safe_string(package_summary, "request_ref") or _artifact_ref(package_step, "request_ref") or _artifact_ref(validate_step, "request_ref")
    validated_request_ref = _safe_string(final_outputs, "validated_request_ref") or _artifact_ref(validate_step, "validated_request_ref")
    request_payload = _read_json(validated_request_ref) or _read_json(request_ref)
    solution_cif_path = _safe_string(final_outputs, "solution_cif_path") or _artifact_ref(solve_step, "solution_cif_path")
    actual_formula = _formula_from_qlip_payload(request_payload) or _formula_from_cif(solution_cif_path)
    expected_formula = material_system
    composition_match: bool | None = None
    if _normalize_formula(expected_formula) and _normalize_formula(actual_formula):
        composition_match = _normalize_formula(expected_formula) == _normalize_formula(actual_formula)
    elif expected_formula or actual_formula:
        composition_match = None

    corpus_ref = _artifact_ref(csp_step, "corpus_ref")
    retrieval_status = "pass" if csp_step and csp_step.get("execution_performed") is True and int(csp_summary.get("exported_cif_count") or 0) > 0 and corpus_ref else "fail" if csp_step else "unknown"
    required_pairs = spp_summary.get("qlip_package_required_pairs") or spp_summary.get("required_pairs") or []
    missing_pairs = spp_summary.get("qlip_package_missing_pairs") or spp_summary.get("missing_pairs") or []
    corpus_quality = spp_summary.get("corpus_quality") if isinstance(spp_summary.get("corpus_quality"), Mapping) else {}
    pot_root = _safe_string(final_outputs, "spp_pot_root") or _safe_string(spp_summary, "pot_root")
    qlip_solve_compatible = spp_summary.get("qlip_solve_compatible")
    qlip_package_present = bool(_safe_string(spp_summary, "spp_qlip_package_json") or _safe_string(spp_summary, "spp_guidance_package_path") or _artifact_ref(package_step, "spp_package_json") or _artifact_ref(package_step, "request_ref"))
    spp_status = "pass" if spp_step and spp_step.get("execution_performed") is True and (qlip_solve_compatible is True or (qlip_package_present and not missing_pairs)) else "fail" if spp_step else "unknown"
    validation_valid = validate_summary.get("valid")
    validation_status = "pass" if validate_step and validate_step.get("execution_performed") is True and validation_valid is True else "fail" if validate_step and validate_step.get("execution_performed") is True else "unknown"
    qlip_status = _safe_string(final_outputs, "final_qlip_status") or _safe_string(solve_summary, "status") or _safe_string(solve_step or {}, "status")
    solve_good_status = qlip_status.lower() in {"optimal", "feasible", "succeeded", "success", "solved"}
    solve_executed = bool(solve_step and solve_step.get("execution_performed") is True)
    solve_status = "pass" if solve_executed and solve_good_status and _path_exists(solution_cif_path) else "fail" if solve_step else "unknown"
    novelty_executed = bool(novelty_step and novelty_step.get("execution_performed") is True)
    novelty_result = final_outputs.get("novelty_result") if isinstance(final_outputs.get("novelty_result"), Mapping) else novelty_summary
    is_novel = novelty_result.get("is_novel") if isinstance(novelty_result, Mapping) else None
    similarity = novelty_result.get("similarity") if isinstance(novelty_result, Mapping) else None
    nearest_match = novelty_result.get("nearest_match") if isinstance(novelty_result, Mapping) else None
    novelty_status = "pass" if novelty_executed and is_novel is not None else "unknown" if not novelty_executed else "unknown"
    failed_step = _failed_or_blocked_step(report)
    recovery_action = _first_recovery_action(report)
    failure_error = failed_step.get("error") if isinstance(failed_step, Mapping) and isinstance(failed_step.get("error"), Mapping) else {}
    failure_classification = (
        _safe_string(recovery_action, "detected_issue")
        if isinstance(recovery_action, Mapping)
        else _safe_string(failure_error, "code")
    )
    failure_recovery_plan = (
        to_json_dict(recovery_action.get("recovery_plan"))
        if isinstance(recovery_action, Mapping) and isinstance(recovery_action.get("recovery_plan"), Mapping)
        else {}
    )

    execution_run_path = _artifact_path(report, "Execution run JSON")
    step_log_path = _artifact_path(report, "Execution step log JSONL")
    raw_tool_count = sum(1 for item in _mapping_list(report, "artifact_index") if "raw result JSON" in _safe_string(item, "label"))
    report_path = str(execution_loop_report_path or _artifact_path(report, "Execution loop report Markdown"))
    provenance_status = "pass" if report_path and execution_run_path and step_log_path and raw_tool_count > 0 else "fail"

    requirement_checks = {
        "composition_requirement": {
            "expected": expected_formula,
            "observed": actual_formula or None,
            "status": _status_for_pass_unknown_fail(composition_match),
            "evidence": validated_request_ref or request_ref or solution_cif_path,
            "notes": "Formula was derived from QLIP request or solution CIF when available.",
        },
        "retrieval_requirement": {
            "expected": "crystal.csp_pack execution with exported retrieval evidence",
            "observed": {
                "executed": bool(csp_step and csp_step.get("execution_performed") is True),
                "neighbor_count": csp_summary.get("neighbor_count"),
                "exported_cif_count": csp_summary.get("exported_cif_count"),
                "corpus_ref": corpus_ref or None,
                "retrieved_evidence_count": csp_summary.get("neighbor_count") or csp_summary.get("exported_cif_count"),
            },
            "status": retrieval_status,
            "evidence": corpus_ref or _artifact_ref(csp_step, "crystal_results_json"),
            "notes": "Retrieval success means evidence was returned/exported; it is not property validation.",
        },
        "spp_guidance_requirement": {
            "expected": "spp.run_pipeline output with QLIP package/POT guidance",
            "observed": {
                "executed": bool(spp_step and spp_step.get("execution_performed") is True),
                "qlip_package_present": qlip_package_present,
                "pot_root": pot_root or None,
                "required_pairs": required_pairs,
                "missing_pairs": missing_pairs,
                "qlip_solve_compatible": qlip_solve_compatible,
                "corpus_quality_status": _safe_string(spp_summary, "corpus_quality_status") or _safe_string(corpus_quality, "corpus_quality_status") or None,
                "detected_formulas": corpus_quality.get("detected_formulas", []) if isinstance(corpus_quality.get("detected_formulas"), list) else [],
                "files_with_all_target_elements": corpus_quality.get("files_with_all_target_elements", []) if isinstance(corpus_quality.get("files_with_all_target_elements"), list) else [],
                "files_with_exact_or_reduced_formula_match": corpus_quality.get("files_with_exact_or_reduced_formula_match", []) if isinstance(corpus_quality.get("files_with_exact_or_reduced_formula_match"), list) else [],
                "files_with_target_cross_pairs": corpus_quality.get("files_with_target_cross_pairs", []) if isinstance(corpus_quality.get("files_with_target_cross_pairs"), list) else [],
                "geometric_pair_counts": corpus_quality.get("geometric_pair_counts", {}) if isinstance(corpus_quality.get("geometric_pair_counts"), Mapping) else {},
            },
            "status": spp_status,
            "evidence": _safe_string(spp_summary, "final_bundle") or _artifact_ref(spp_step, "spp_final_bundle_path") or _artifact_ref(package_step, "spp_package_json"),
            "notes": "SPP/POT coverage is assessed from package metadata and reported pair coverage only.",
        },
        "validation_requirement": {
            "expected": "qlip.validate_request executed and valid=true",
            "observed": {
                "executed": bool(validate_step and validate_step.get("execution_performed") is True),
                "valid": validation_valid,
                "validation_error_codes": _string_list(validate_summary, "validation_error_codes"),
                "data_diagnostics": validate_summary.get("capabilities"),
            },
            "status": validation_status,
            "evidence": validated_request_ref,
            "notes": "Validation reports request/package validity, not generated-crystal property success.",
        },
        "solve_requirement": {
            "expected": "qlip.solve executed with feasible/optimal result and solution CIF",
            "observed": {
                "executed": solve_executed,
                "qlip_status": qlip_status or None,
                "objective_value": final_outputs.get("final_objective_value") if isinstance(final_outputs, Mapping) else solve_summary.get("objective_value"),
                "solution_cif_path": solution_cif_path or None,
                "solution_cif_exists": _path_exists(solution_cif_path),
            },
            "status": solve_status,
            "evidence": solution_cif_path,
            "notes": "Solver status is interpreted only against the formulated QLIP objective.",
        },
        "novelty_requirement": {
            "expected": "crystal.novelty_check executed with explicit novelty result",
            "observed": {
                "executed": novelty_executed,
                "is_novel": is_novel,
                "similarity_score": similarity,
                "nearest_match": nearest_match,
            },
            "status": novelty_status,
            "evidence": _safe_string(novelty_step or {}, "raw_result_ref"),
            "notes": "Non-novel means rediscovery or close analogue, not execution failure.",
        },
        "provenance_requirement": {
            "expected": "report, raw responses, execution_step_log, execution_run, and solution path records",
            "observed": {
                "report_files_exist": bool(report_path),
                "raw_tool_response_count": raw_tool_count,
                "execution_step_log": step_log_path or None,
                "execution_run": execution_run_path or None,
                "solution_cif_path_recorded": bool(solution_cif_path),
            },
            "status": provenance_status,
            "evidence": report_path,
            "notes": "Provenance is assessed from artifact references recorded in the execution-loop report.",
        },
    }

    execution_stage_names = ["crystal.csp_pack", "spp.run_pipeline", "qlip.validate_request", "qlip.solve", "crystal.novelty_check"]
    execution_success = sum(20 for name in execution_stage_names if (_latest_step(report, name) or {}).get("status") == "succeeded")
    request_fulfilment = (
        50 * _score_from_status(requirement_checks["composition_requirement"]["status"]) / 100
        + 30 * (sum(1 for key in ("retrieval_requirement", "spp_guidance_requirement", "validation_requirement", "solve_requirement") if requirement_checks[key]["status"] == "pass") / 4)
        + 20 * (sum(1 for key in ("retrieval_requirement", "spp_guidance_requirement", "solve_requirement", "provenance_requirement") if requirement_checks[key]["status"] == "pass") / 4)
    )
    evidence_quality = (
        40 * _score_from_status(retrieval_status) / 100
        + 40 * _score_from_status(spp_status) / 100
        + 20 * _score_from_status(provenance_status) / 100
    )
    solve_quality = (
        (30 if validation_status == "pass" else 0)
        + (40 if solve_executed and solve_good_status else 0)
        + (30 if _path_exists(solution_cif_path) else 0)
    )
    provenance_score = _score_from_status(provenance_status)
    novelty_score: int | None
    if not novelty_executed or is_novel is None:
        novelty_score = None
    elif is_novel is True:
        novelty_score = 90
    else:
        novelty_score = 20
    overall_score = (
        0.25 * request_fulfilment
        + 0.25 * execution_success
        + 0.20 * evidence_quality
        + 0.20 * solve_quality
        + 0.10 * provenance_score
    )

    final_status = "completed" if solve_status == "pass" and validation_status == "pass" else "partial" if any(check["status"] == "pass" for check in requirement_checks.values()) else "failed"
    warnings: list[str] = []
    errors: list[str] = []
    if novelty_score is None:
        warnings.append("Novelty was not evaluated or did not return an explicit result.")
    if not _path_exists(solution_cif_path):
        warnings.append("No existing solution CIF was recorded.")
    if validation_status == "fail":
        errors.extend(_string_list(validate_summary, "validation_error_codes"))
    if failed_step:
        failed_tool = _safe_string(failed_step, "tool_name")
        failed_code = failure_classification or _safe_string(failure_error, "code")
        if failed_tool or failed_code:
            errors.append(f"{failed_tool}: {failed_code}".strip(": "))

    recommended_next_actions = []
    if failure_recovery_plan:
        hint = _safe_string(failure_recovery_plan, "next_step_hint") or _safe_string(failure_recovery_plan, "hint")
        if hint:
            recommended_next_actions.append(hint)
    canonical_failure_hint = _canonical_recovery_hint(failure_classification)
    if canonical_failure_hint and not any("Revise the QLIP formulation" in item for item in recommended_next_actions):
        recommended_next_actions.insert(0, canonical_failure_hint)
    if is_novel is False:
        recommended_next_actions.append("If novelty is required, modify retrieval constraints or novelty threshold and rerun.")
    if solve_status != "pass":
        recommended_next_actions.append("Inspect QLIP validation/solve diagnostics before treating this as a generated-crystal success.")
    if retrieval_status != "pass":
        recommended_next_actions.append("Improve retrieval corpus/export coverage and rerun crystal.csp_pack.")
    recommended_next_actions.append("Add a property-predictor layer later if the text request includes target properties.")

    scores = {
        "overall_score_0_100": _bounded(overall_score),
        "request_fulfilment_score_0_100": _bounded(request_fulfilment),
        "execution_success_score_0_100": _bounded(execution_success),
        "evidence_quality_score_0_100": _bounded(evidence_quality),
        "solve_quality_score_0_100": _bounded(solve_quality),
        "novelty_score_0_100": novelty_score,
        "provenance_score_0_100": _bounded(provenance_score),
        "rediscovery_flag": is_novel is False,
    }
    evaluator_summary = (
        "The workflow produced a validated solved crystal candidate with traceable evidence."
        if final_status == "completed"
        else "The workflow is only partially fulfilled; at least one validation, solve, artifact, or evidence requirement is missing."
        if final_status == "partial"
        else "The workflow did not produce enough completed stages to satisfy the text-to-crystal request."
    )
    result = {
        "schema_version": WORKFLOW_EVALUATION_SCHEMA_VERSION,
        "run_id": run_id,
        "goal": goal,
        "material_system": material_system,
        "plan_source": plan_source_name,
        "backend": backend,
        "final_status": final_status,
        "evaluator_summary": evaluator_summary,
        "scores": scores,
        "requirement_checks": requirement_checks,
        "evidence_checks": {
            "retrieval": requirement_checks["retrieval_requirement"],
            "spp_guidance": requirement_checks["spp_guidance_requirement"],
        },
        "execution_checks": {
            "validation": requirement_checks["validation_requirement"],
            "solve": requirement_checks["solve_requirement"],
        },
        "failure_assessment": {
            "failed_tool": _safe_string(failed_step, "tool_name") if isinstance(failed_step, Mapping) else None,
            "tool_status": _safe_string(failed_step, "status") if isinstance(failed_step, Mapping) else None,
            "error_code": _safe_string(failure_error, "code") if isinstance(failure_error, Mapping) else None,
            "error_message": _safe_string(failure_error, "message") if isinstance(failure_error, Mapping) else None,
            "classification": failure_classification or None,
            "qlip_status": qlip_status or None,
            "recovery_recommendation": to_json_dict(recovery_action) if isinstance(recovery_action, Mapping) else None,
            "recovery_plan": failure_recovery_plan or None,
        },
        "novelty_assessment": requirement_checks["novelty_requirement"],
        "solution_assessment": {
            "solution_cif_path": solution_cif_path or None,
            "qlip_status": qlip_status or None,
            "objective_value": requirement_checks["solve_requirement"]["observed"]["objective_value"],
            "formula": actual_formula or None,
            "status": solve_status,
        },
        "provenance_assessment": requirement_checks["provenance_requirement"],
        "warnings": warnings,
        "errors": errors,
        "recommended_next_actions": recommended_next_actions,
        "artifact_refs": {
            "execution_loop_report": report_path or None,
            "execution_run": execution_run_path or None,
            "execution_step_log": step_log_path or None,
            "request_ref": request_ref or None,
            "validated_request_ref": validated_request_ref or None,
            "solution_cif_path": solution_cif_path or None,
        },
    }
    assert_json_serializable(result)
    return result


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "Not available"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _markdown_for_evaluation(evaluation: Mapping[str, Any]) -> str:
    payload = to_json_dict(evaluation)
    scores = payload.get("scores") if isinstance(payload.get("scores"), Mapping) else {}
    reqs = payload.get("requirement_checks") if isinstance(payload.get("requirement_checks"), Mapping) else {}
    solution = payload.get("solution_assessment") if isinstance(payload.get("solution_assessment"), Mapping) else {}
    novelty = payload.get("novelty_assessment") if isinstance(payload.get("novelty_assessment"), Mapping) else {}
    artifacts = payload.get("artifact_refs") if isinstance(payload.get("artifact_refs"), Mapping) else {}
    failure = payload.get("failure_assessment") if isinstance(payload.get("failure_assessment"), Mapping) else {}
    failure_hint = ""
    recovery_plan = failure.get("recovery_plan") if isinstance(failure.get("recovery_plan"), Mapping) else {}
    if isinstance(recovery_plan, Mapping):
        failure_hint = _safe_string(recovery_plan, "next_step_hint") or _safe_string(recovery_plan, "hint")
    canonical_failure_hint = _canonical_recovery_hint(_safe_string(failure, "classification"))
    recovery_recommendation = canonical_failure_hint or failure_hint
    verdict = _safe_string(payload, "final_status", "unknown")
    answer = _safe_string(payload, "evaluator_summary")

    score_rows = [
        ("overall", scores.get("overall_score_0_100")),
        ("request fulfilment", scores.get("request_fulfilment_score_0_100")),
        ("execution success", scores.get("execution_success_score_0_100")),
        ("evidence quality", scores.get("evidence_quality_score_0_100")),
        ("solve quality", scores.get("solve_quality_score_0_100")),
        ("novelty", scores.get("novelty_score_0_100")),
        ("provenance", scores.get("provenance_score_0_100")),
    ]
    lines = [
        "# Workflow Evaluation Report",
        "",
        "## Executive Verdict",
        f"- verdict: {verdict}",
        "",
        answer,
        "",
        "## Original Request",
        f"- goal: {_fmt(payload.get('goal'))}",
        f"- material_system: {_fmt(payload.get('material_system'))}",
        f"- plan_source: {_fmt(payload.get('plan_source'))}",
        f"- backend: {_fmt(payload.get('backend'))}",
        "",
        "## Score Summary",
        "| score | value |",
        "| --- | --- |",
    ]
    lines.extend(f"| {name} | {_fmt(value)} |" for name, value in score_rows)
    lines.extend(["", "## Requirement Fulfilment"])
    for key, check in reqs.items():
        if not isinstance(check, Mapping):
            continue
        lines.extend(
            [
                f"### {key}",
                f"- expected: {_fmt(check.get('expected'))}",
                f"- observed: {_fmt(check.get('observed'))}",
                f"- status: {_fmt(check.get('status'))}",
                f"- evidence: {_fmt(check.get('evidence'))}",
                f"- notes: {_fmt(check.get('notes'))}",
                "",
            ]
        )
    lines.extend(
        [
            "## Evidence Chain",
            f"text request -> {_fmt(payload.get('goal'))}",
            f"-> retrieval evidence -> {_fmt(reqs.get('retrieval_requirement', {}).get('evidence') if isinstance(reqs.get('retrieval_requirement'), Mapping) else None)}",
            f"-> SPP POT root / pair coverage -> {_fmt(reqs.get('spp_guidance_requirement', {}).get('observed') if isinstance(reqs.get('spp_guidance_requirement'), Mapping) else None)}",
            f"-> QLIP validated request -> {_fmt(artifacts.get('validated_request_ref'))}",
            f"-> solution CIF -> {_fmt(artifacts.get('solution_cif_path'))}",
            f"-> novelty result -> {_fmt(novelty.get('observed') if isinstance(novelty, Mapping) else None)}",
            "",
            "## Failure Diagnostics",
            f"- failed tool: {_fmt(failure.get('failed_tool'))}",
            f"- tool status: {_fmt(failure.get('tool_status'))}",
            f"- error code: {_fmt(failure.get('error_code'))}",
            f"- classification: {_fmt(failure.get('classification'))}",
            f"- QLIP status: {_fmt(failure.get('qlip_status'))}",
            f"- recovery recommendation: {_fmt(recovery_recommendation)}",
            f"- recovery plan: {_fmt(failure.get('recovery_plan'))}",
            "",
            "## Generated Crystal",
            f"- solution CIF path: {_fmt(solution.get('solution_cif_path'))}",
            f"- QLIP status: {_fmt(solution.get('qlip_status'))}",
            f"- objective value: {_fmt(solution.get('objective_value'))}",
            f"- formula if extractable: {_fmt(solution.get('formula'))}",
            f"- warnings if formula unknown: {'Formula could not be extracted.' if not solution.get('formula') else 'None'}",
            "",
            "## Novelty / Rediscovery",
            f"- is_novel: {_fmt(novelty.get('observed', {}).get('is_novel') if isinstance(novelty.get('observed'), Mapping) else None)}",
            f"- nearest match / similarity: {_fmt(novelty.get('observed', {}).get('nearest_match') if isinstance(novelty.get('observed'), Mapping) else None)} / {_fmt(novelty.get('observed', {}).get('similarity_score') if isinstance(novelty.get('observed'), Mapping) else None)}",
            f"- interpretation: {_novelty_interpretation(novelty)}",
            "",
            "## Limitations",
            "- No property predictor was used unless explicit property evidence is present in the artifacts.",
            "- Semantic retrieval does not prove target property success.",
            "- Novelty is structural/fingerprint based, not experimental validation.",
            "- Solver optimality is with respect to the formulated QLIP objective only.",
            "",
            "## Recommended Next Actions",
        ]
    )
    actions = payload.get("recommended_next_actions")
    if isinstance(actions, list) and actions:
        lines.extend(f"- {action}" for action in actions)
    else:
        lines.append("- No next actions were recorded.")
    lines.append("")
    return "\n".join(lines)


def _novelty_interpretation(novelty: Mapping[str, Any]) -> str:
    observed = novelty.get("observed") if isinstance(novelty.get("observed"), Mapping) else {}
    is_novel = observed.get("is_novel") if isinstance(observed, Mapping) else None
    if is_novel is True:
        return "novel: candidate appears structurally distinct"
    if is_novel is False:
        return "non-novel: likely rediscovery or close analogue"
    return "unknown: novelty not evaluated"


def write_workflow_evaluation(
    evaluation: Mapping[str, Any],
    out_dir: str | Path,
) -> dict[str, Any]:
    evaluation_dict = to_json_dict(evaluation)
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "workflow_evaluation.json"
    md_path = root / "workflow_evaluation.md"
    _write_json(json_path, evaluation_dict)
    _write_text(md_path, _markdown_for_evaluation(evaluation_dict))
    result = {
        "schema_version": WORKFLOW_EVALUATION_WRITE_SCHEMA_VERSION,
        "evaluation_json_path": str(json_path),
        "evaluation_markdown_path": str(md_path),
        "artifact_paths": [str(json_path), str(md_path)],
    }
    assert_json_serializable(result)
    return result


__all__ = [
    "WORKFLOW_EVALUATION_SCHEMA_VERSION",
    "WORKFLOW_EVALUATION_WRITE_SCHEMA_VERSION",
    "build_workflow_evaluation",
    "load_demo_artifacts_for_evaluation",
    "write_workflow_evaluation",
]
