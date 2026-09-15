from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .schemas import assert_json_serializable, to_json_dict
from .sequence_diagram import build_demo_loop_mermaid_sequence
from .trace_render import render_agentic_llm_trace_markdown

EXECUTION_LOOP_REPORT_SCHEMA_VERSION = "agentic_csp.execution_loop_report.v1"
EXECUTION_LOOP_REPORT_WRITE_SCHEMA_VERSION = "agentic_csp.execution_loop_report_write.v1"


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str):
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


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _tool_hints_from_run_plan(run_plan: Mapping[str, Any]) -> list[str]:
    plan_as_text = run_plan.get("plan_as_text")
    if not isinstance(plan_as_text, str):
        return []
    hints: list[str] = []
    for line in plan_as_text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        for prefix in ("tool_hint:", "tool_hint="):
            if lowered.startswith(prefix):
                hint = stripped[len(prefix) :].strip()
                if hint and hint not in hints:
                    hints.append(hint)
                break
    return hints


def _placeholder_refs(step: Mapping[str, Any]) -> list[str]:
    audit = step.get("audit")
    if not isinstance(audit, Mapping):
        return []
    return [
        str(item)
        for item in audit.get("placeholder_refs", [])
        if isinstance(item, str) and item.strip()
    ] if isinstance(audit.get("placeholder_refs"), list) else []


def _artifact_path_entries(
    planner_compile_run: Mapping[str, Any],
    parse_report_path: str | None,
    executable_plan_path: str | None,
    executable_plan_report_path: str | None,
    execution_run: Mapping[str, Any],
    planner_trace_markdown_path: str | None,
    recovery_attempt: Mapping[str, Any] | None,
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []

    trace_write = planner_compile_run.get("trace_write")
    if isinstance(trace_write, Mapping):
        trace_json = _safe_string(trace_write, "trace_json_path")
        if trace_json:
            entries.append({"label": "LLM trace JSON", "path": trace_json})
    if isinstance(planner_trace_markdown_path, str) and planner_trace_markdown_path.strip():
        entries.append({"label": "LLM trace Markdown", "path": planner_trace_markdown_path})

    for label, path in (
        ("Tool parse report JSON", parse_report_path),
        ("Executable plan JSON", executable_plan_path),
        ("Executable plan report JSON", executable_plan_report_path),
        (
            "Execution run JSON",
            _safe_string(execution_run.get("artifact_paths", {}), "execution_run_json")
            if isinstance(execution_run.get("artifact_paths"), Mapping)
            else "",
        ),
        (
            "Execution step log JSONL",
            _safe_string(execution_run.get("artifact_paths", {}), "execution_step_log_jsonl")
            if isinstance(execution_run.get("artifact_paths"), Mapping)
            else "",
        ),
    ):
        if isinstance(path, str) and path.strip():
            entries.append({"label": label, "path": path})

    for step_result in _mapping_list(execution_run, "step_results"):
        tool_name = _safe_string(step_result, "tool_name", "unknown.tool")
        raw_ref = step_result.get("raw_result_ref")
        if isinstance(raw_ref, str) and raw_ref.strip():
            entries.append({"label": f"{tool_name} raw result JSON", "path": raw_ref})
        for artifact in _mapping_list(step_result, "artifact_refs"):
            value = _safe_string(artifact, "value")
            ref_name = _safe_string(artifact, "ref_name")
            if value and ref_name:
                entries.append({"label": f"{tool_name} {ref_name}", "path": value})

    if isinstance(recovery_attempt, Mapping):
        corrected_request_path = _safe_string(recovery_attempt, "corrected_request_path")
        if corrected_request_path:
            entries.append({"label": "Recovery corrected QLIP request JSON", "path": corrected_request_path})
        recovery_step_log_path = _safe_string(recovery_attempt, "recovery_step_log_path")
        if recovery_step_log_path:
            entries.append({"label": "Recovery step log JSONL", "path": recovery_step_log_path})
        retry_validation = (
            to_json_dict(recovery_attempt.get("retry_validation"))
            if isinstance(recovery_attempt.get("retry_validation"), Mapping)
            else {}
        )
        retry_solve = (
            to_json_dict(recovery_attempt.get("solve"))
            if isinstance(recovery_attempt.get("solve"), Mapping)
            else {}
        )
        retry_novelty = (
            to_json_dict(recovery_attempt.get("novelty"))
            if isinstance(recovery_attempt.get("novelty"), Mapping)
            else {}
        )
        for label, path in (
            ("Retry validated request JSON", _safe_string(retry_validation, "validated_request_ref")),
            ("Retry raw validation response JSON", _safe_string(retry_validation, "raw_validation_response_ref")),
            ("Retry raw solve response JSON", _safe_string(retry_solve, "raw_solve_response_ref")),
            ("Retry raw novelty response JSON", _safe_string(retry_novelty, "raw_novelty_response_ref")),
        ):
            if path:
                entries.append({"label": label, "path": path})

    unique_entries: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        key = (entry["label"], entry["path"])
        if key not in seen:
            seen.add(key)
            unique_entries.append(entry)
    return unique_entries


def _report_run_id(
    planner_compile_run: Mapping[str, Any],
    run_plan: Mapping[str, Any],
    execution_run: Mapping[str, Any],
) -> str:
    top_level_run_id = _safe_string(planner_compile_run, "run_id")
    if top_level_run_id:
        return top_level_run_id
    run_plan_run_id = _safe_string(run_plan, "run_id")
    if run_plan_run_id:
        return run_plan_run_id
    for step in _mapping_list(execution_run, "step_results"):
        arguments = step.get("arguments")
        if isinstance(arguments, Mapping):
            case_id = _safe_string(arguments, "case_id")
            if case_id:
                return case_id
    return ""


def _step_log_rows(
    execution_run: Mapping[str, Any],
    tool_execution_rows: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if tool_execution_rows:
        return [to_json_dict(item) for item in tool_execution_rows]

    rows: list[dict[str, Any]] = []
    for step in _mapping_list(execution_run, "step_results"):
        status = _safe_string(step, "status")
        decision = (
            "continue"
            if status == "succeeded"
            else "blocked"
            if status == "blocked"
            else "stop_on_failure"
        )
        rows.append(
            {
                "step_index": int(step.get("step_index", len(rows))),
                "tool_name": _safe_string(step, "tool_name"),
                "arguments": to_json_dict(step.get("arguments", {}))
                if isinstance(step.get("arguments"), Mapping)
                else {},
                "execution_performed": bool(step.get("execution_performed")),
                "status": status,
                "output_summary": to_json_dict(step.get("output_summary", {}))
                if isinstance(step.get("output_summary"), Mapping)
                else {},
                "artifact_refs": _mapping_list(step, "artifact_refs"),
                "error": to_json_dict(step.get("error"))
                if isinstance(step.get("error"), Mapping)
                else None,
                "decision": decision,
            }
        )
    return rows


def _artifact_ref_map(tool_execution_log: list[dict[str, Any]]) -> dict[str, str]:
    refs: dict[str, str] = {}
    for row in tool_execution_log:
        for artifact in _mapping_list(row, "artifact_refs"):
            ref_name = _safe_string(artifact, "ref_name")
            ref_value = _safe_string(artifact, "value")
            if ref_name and ref_value:
                refs[ref_name] = ref_value
    return refs


def _latest_step(tool_execution_log: list[dict[str, Any]], tool_name: str) -> dict[str, Any] | None:
    for row in reversed(tool_execution_log):
        if _safe_string(row, "tool_name") == tool_name:
            return row
    return None


def _final_outputs(
    tool_execution_log: list[dict[str, Any]],
    execution_run: Mapping[str, Any],
    result_notes: Mapping[str, Any],
    recovery_attempt: Mapping[str, Any] | None,
) -> dict[str, Any]:
    artifact_refs = _artifact_ref_map(tool_execution_log)
    novelty_row = _latest_step(tool_execution_log, "crystal.novelty_check")
    qlip_row = _latest_step(tool_execution_log, "qlip.solve")
    qlip_validation_row = _latest_step(tool_execution_log, "qlip.validate_request")
    spp_row = _latest_step(tool_execution_log, "spp.run_pipeline")
    novelty_summary = (
        to_json_dict(novelty_row.get("output_summary", {}))
        if isinstance(novelty_row, Mapping) and isinstance(novelty_row.get("output_summary"), Mapping)
        else {}
    )
    qlip_summary = (
        to_json_dict(qlip_row.get("output_summary", {}))
        if isinstance(qlip_row, Mapping) and isinstance(qlip_row.get("output_summary"), Mapping)
        else {}
    )
    qlip_validation_summary = (
        to_json_dict(qlip_validation_row.get("output_summary", {}))
        if isinstance(qlip_validation_row, Mapping) and isinstance(qlip_validation_row.get("output_summary"), Mapping)
        else {}
    )
    spp_summary = (
        to_json_dict(spp_row.get("output_summary", {}))
        if isinstance(spp_row, Mapping) and isinstance(spp_row.get("output_summary"), Mapping)
        else {}
    )
    recovery_dict = to_json_dict(recovery_attempt) if isinstance(recovery_attempt, Mapping) else {}
    recovery_retry_validation = (
        to_json_dict(recovery_dict.get("retry_validation"))
        if isinstance(recovery_dict.get("retry_validation"), Mapping)
        else {}
    )
    recovery_solve = (
        to_json_dict(recovery_dict.get("solve"))
        if isinstance(recovery_dict.get("solve"), Mapping)
        else {}
    )
    recovery_novelty = (
        to_json_dict(recovery_dict.get("novelty"))
        if isinstance(recovery_dict.get("novelty"), Mapping)
        else {}
    )
    validation_status = (
        "invalid"
        if recovery_retry_validation.get("valid") is False
        else "valid"
        if recovery_retry_validation.get("valid") is True
        else "invalid"
        if qlip_validation_summary.get("valid") is False
        else "valid"
        if qlip_validation_summary.get("valid") is True
        else None
    )
    recovery_action = ""
    recovery_reason = ""
    next_step_hint = ""
    failure_handling = (
        to_json_dict(result_notes.get("failure_handling"))
        if isinstance(result_notes.get("failure_handling"), Mapping)
        else {}
    )
    if isinstance(failure_handling.get("actions"), list):
        for action in failure_handling["actions"]:
            if not isinstance(action, Mapping):
                continue
            if _safe_string(action, "action_type") != "repackage_qlip_request":
                continue
            recovery_action = _safe_string(action, "action_type")
            recovery_reason = _safe_string(action, "recovery_reason")
            next_step_hint = _safe_string(action, "next_step_hint")
            break
    result = {
        "candidate_cif_path": artifact_refs.get("candidate_cif_path"),
        "solution_cif_path": recovery_solve.get("solution_cif_path") or artifact_refs.get("solution_cif_path"),
        "spp_package_ref": artifact_refs.get("spp_package_ref"),
        "spp_bundle_path": artifact_refs.get("spp_bundle_path") or artifact_refs.get("spp_final_bundle_path"),
        "spp_output": {
            "run_root": spp_summary.get("run_root"),
            "final_bundle": spp_summary.get("final_bundle"),
            "fit_spp_root": spp_summary.get("fit_spp_root"),
            "scaled_spp_root": spp_summary.get("scaled_spp_root"),
        } if spp_summary else None,
        "spp_qlip_package": {
            "status": spp_summary.get("qlip_package_status"),
            "guidance_package_path": spp_summary.get("spp_guidance_package_path")
            or artifact_refs.get("spp_guidance_package_path"),
            "package_json_path": spp_summary.get("spp_qlip_package_json")
            or artifact_refs.get("spp_qlip_package_json"),
            "compatibility": spp_summary.get("qlip_package_compatibility"),
            "qlip_solve_compatible": spp_summary.get("qlip_solve_compatible"),
            "context": spp_summary.get("qlip_package_context"),
            "pot_root": spp_summary.get("pot_root"),
            "required_pairs": spp_summary.get("qlip_package_required_pairs"),
            "missing_pairs": spp_summary.get("qlip_package_missing_pairs"),
            "missing": spp_summary.get("qlip_package_missing"),
            "errors": spp_summary.get("qlip_package_errors"),
            "fresh_generation": spp_summary.get("fresh_generation"),
            "corpus_quality": spp_summary.get("corpus_quality"),
            "corpus_quality_status": spp_summary.get("corpus_quality_status"),
            "detected_formulas": spp_summary.get("detected_formulas"),
            "files_with_all_target_elements": spp_summary.get("files_with_all_target_elements"),
            "files_with_exact_or_reduced_formula_match": spp_summary.get("files_with_exact_or_reduced_formula_match"),
            "files_with_target_cross_pairs": spp_summary.get("files_with_target_cross_pairs"),
            "geometric_pair_counts": spp_summary.get("geometric_pair_counts"),
        } if spp_summary else None,
        "spp_qlip_package_status": spp_summary.get("qlip_package_status"),
        "spp_qlip_solve_compatible": spp_summary.get("qlip_solve_compatible"),
        "spp_qlip_package_missing": spp_summary.get("qlip_package_missing"),
        "spp_qlip_required_pairs": spp_summary.get("qlip_package_required_pairs"),
        "spp_qlip_missing_pairs": spp_summary.get("qlip_package_missing_pairs"),
        "spp_qlip_package_errors": spp_summary.get("qlip_package_errors"),
        "spp_corpus_quality_status": spp_summary.get("corpus_quality_status"),
        "spp_corpus_quality": spp_summary.get("corpus_quality"),
        "spp_pot_root": spp_summary.get("pot_root") or artifact_refs.get("pot_root"),
        "request_ref": recovery_dict.get("corrected_request_path") or artifact_refs.get("request_ref"),
        "validated_request_ref": recovery_retry_validation.get("validated_request_ref") or artifact_refs.get("validated_request_ref"),
        "qlip_packaging_validation_status": validation_status,
        "qlip_validation_status": validation_status,
        "qlip_validation_errors": recovery_retry_validation.get("validation_errors") or qlip_validation_summary.get("validation_errors"),
        "qlip_validation_warnings": qlip_validation_summary.get("validation_warnings"),
        "proposed_recovery_action": recovery_action or None,
        "recovery_reason": recovery_reason or None,
        "recovery_next_step_hint": next_step_hint or None,
        "novelty_result": (
            {
                "is_novel": recovery_novelty.get("is_novel"),
            }
            if recovery_novelty.get("attempted") is True
            else novelty_summary if novelty_summary else None
        ),
        "final_qlip_status": recovery_solve.get("status") or qlip_summary.get("status"),
        "qlip_solve_attempted": (
            bool(recovery_solve.get("attempted"))
            if recovery_solve.get("attempted") is not None
            else bool(isinstance(qlip_row, Mapping) and qlip_row.get("execution_performed") is True)
        ),
        "final_objective_value": qlip_summary.get("objective_value"),
        "final_execution_status": _safe_string(execution_run, "status"),
    }
    assert_json_serializable(result)
    return result


def _demo_summary(run_summary: Mapping[str, Any], final_outputs: Mapping[str, Any]) -> dict[str, Any]:
    executed_tools = _string_list(run_summary, "executed_tools")
    blocked_tools = _string_list(run_summary, "blocked_tools")
    candidate_status = (
        "solution generated"
        if _safe_string(final_outputs, "solution_cif_path")
        else "candidate generated"
        if _safe_string(final_outputs, "candidate_cif_path")
        else "no final CIF output"
    )
    novelty_result = final_outputs.get("novelty_result")
    novelty_status = (
        "novelty not checked"
        if not isinstance(novelty_result, Mapping)
        else "novel"
        if novelty_result.get("is_novel") is True
        else "not novel"
        if novelty_result.get("is_novel") is False
        else "novelty inconclusive"
    )
    sentence = (
        f"Run {_safe_string(run_summary, 'run_id', 'unknown')} ended with status "
        f"{_safe_string(run_summary, 'status', 'unknown')} after {len(executed_tools)} executed "
        f"tool{'s' if len(executed_tools) != 1 else ''} and {len(blocked_tools)} blocked "
        f"tool{'s' if len(blocked_tools) != 1 else ''}."
    )
    result = {
        "status_sentence": sentence,
        "run_id": _safe_string(run_summary, "run_id", "unknown"),
        "status": _safe_string(run_summary, "status"),
        "execution_performed": bool(run_summary.get("execution_performed")),
        "executed_tool_count": len(executed_tools),
        "blocked_tool_count": len(blocked_tools),
        "final_solution_candidate_status": candidate_status,
        "final_novelty_status": novelty_status,
    }
    assert_json_serializable(result)
    return result


def _plan_source_metadata(
    planner_compile_run: Mapping[str, Any],
    run_plan: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = run_plan.get("metadata") if isinstance(run_plan.get("metadata"), Mapping) else {}
    plan_source = _safe_string(planner_compile_run, "plan_source") or _safe_string(
        metadata, "plan_source", "live_llm"
    )
    material_system = _safe_string(planner_compile_run, "material_system") or _safe_string(
        metadata, "material_system"
    )
    mcp_backend = _safe_string(planner_compile_run, "mcp_backend")
    crystal_export_mode = _safe_string(planner_compile_run, "crystal_export_mode") or _safe_string(
        metadata, "crystal_export_mode", "safe"
    )
    crystal_demo_export_enabled = bool(
        planner_compile_run.get(
            "crystal_demo_export_enabled",
            metadata.get("crystal_demo_export_enabled", False) if isinstance(metadata, Mapping) else False,
        )
    )
    live_llm_used = bool(
        planner_compile_run.get("live_llm_used", plan_source == "live_llm")
    )
    deterministic_showcase = plan_source == "deterministic_showcase"
    warning = (
        "Fake MCP backend is in use for this demo run."
        if mcp_backend == "fake"
        else "Crystal-DB demo export is enabled for this configured showcase run."
        if mcp_backend == "configured" and crystal_demo_export_enabled
        else ""
    )
    result = {
        "plan_source": plan_source,
        "live_llm_used": live_llm_used,
        "deterministic_showcase": deterministic_showcase,
        "mcp_backend": mcp_backend,
        "material_system": material_system,
        "crystal_export_mode": crystal_export_mode,
        "crystal_demo_export_enabled": crystal_demo_export_enabled,
        "warning": warning,
    }
    assert_json_serializable(result)
    return result


def _what_this_demonstrates() -> list[str]:
    return [
        "LLM produced a structured plan.",
        "Tool hints were parsed.",
        "Executable plan was built.",
        "Gated executor used parsed plan.",
        "Tools were called through adapters.",
        "Outputs and artifact refs were captured.",
        "No old hardcoded pipeline shortcut was used.",
    ]


def _what_this_demonstrates_for_source(plan_source: Mapping[str, Any]) -> list[str]:
    if bool(plan_source.get("deterministic_showcase")):
        lines = [
            "A deterministic showcase builder produced a structured plan.",
            "Tool hints were parsed.",
            "Executable plan was built.",
            "Gated executor used parsed plan.",
            "Tools were called through adapters.",
            "Outputs and artifact refs were captured.",
            "No old hardcoded pipeline shortcut was used.",
            "This run used a deterministic showcase plan rather than a live LLM-generated plan.",
        ]
    else:
        lines = _what_this_demonstrates()
        if bool(plan_source.get("live_llm_used")):
            lines.append("This run used a live LLM-generated plan.")
    return lines


def build_execution_loop_report(
    *,
    planner_compile_run: Mapping[str, Any],
    parse_report: Mapping[str, Any],
    executable_plan: Mapping[str, Any],
    executable_plan_report: Mapping[str, Any],
    execution_run: Mapping[str, Any],
    tool_execution_rows: list[dict[str, Any]] | None = None,
    result_inspection: Mapping[str, Any] | None = None,
    failure_handling: Mapping[str, Any] | None = None,
    partial_success: Mapping[str, Any] | None = None,
    continuation_summary: Mapping[str, Any] | None = None,
    recovery_attempt: Mapping[str, Any] | None = None,
    parse_report_path: str | None = None,
    executable_plan_path: str | None = None,
    executable_plan_report_path: str | None = None,
    planner_trace_markdown_path: str | None = None,
) -> dict[str, Any]:
    planner_dict = to_json_dict(planner_compile_run)
    parse_dict = to_json_dict(parse_report)
    executable_plan_dict = to_json_dict(executable_plan)
    executable_plan_report_dict = to_json_dict(executable_plan_report)
    execution_run_dict = to_json_dict(execution_run)
    run_plan = (
        to_json_dict(planner_dict.get("run_plan", {}))
        if isinstance(planner_dict.get("run_plan"), Mapping)
        else {}
    )
    execution_rows = _step_log_rows(execution_run_dict, tool_execution_rows)

    result_notes: dict[str, Any] = {}
    for key, value in (
        ("result_inspection", result_inspection),
        ("failure_handling", failure_handling),
        ("partial_success", partial_success),
        ("continuation_summary", continuation_summary),
    ):
        if isinstance(value, Mapping):
            result_notes[key] = to_json_dict(value)

    run_summary = {
        "run_id": _report_run_id(planner_dict, run_plan, execution_run_dict),
        "status": _safe_string(execution_run_dict, "status"),
        "execution_performed": bool(execution_run_dict.get("execution_performed")),
        "executed_tools": _string_list(execution_run_dict, "executed_tool_sequence"),
        "blocked_tools": _string_list(execution_run_dict, "blocked_tool_sequence"),
        "total_steps": len(_mapping_list(execution_run_dict, "step_results")),
    }
    plan_source = _plan_source_metadata(planner_dict, run_plan)
    demo_summary = _demo_summary(run_summary, {})
    demo_summary["material_or_example"] = _safe_string(plan_source, "material_system", "Not specified")
    demo_summary["backend"] = _safe_string(plan_source, "mcp_backend", "Not specified")
    demo_summary["plan_source"] = _safe_string(plan_source, "plan_source", "live_llm")
    demo_summary["crystal_export_mode"] = _safe_string(plan_source, "crystal_export_mode", "safe")
    demo_summary["crystal_demo_export_enabled"] = bool(plan_source.get("crystal_demo_export_enabled"))
    sequence_diagram_markdown = build_demo_loop_mermaid_sequence(
        run_plan=run_plan,
        compile_result=parse_dict,
        executable_plan=executable_plan_dict,
        execution_run=execution_run_dict,
        tool_parse_report=parse_dict,
    )

    artifact_index = _artifact_path_entries(
        planner_dict,
        parse_report_path,
        executable_plan_path,
        executable_plan_report_path,
        execution_run_dict,
        planner_trace_markdown_path,
        recovery_attempt,
    )

    final_outputs = _final_outputs(execution_rows, execution_run_dict, result_notes, recovery_attempt)
    demo_summary = _demo_summary(run_summary, final_outputs)
    demo_summary["material_or_example"] = _safe_string(plan_source, "material_system", "Not specified")
    demo_summary["backend"] = _safe_string(plan_source, "mcp_backend", "Not specified")
    demo_summary["plan_source"] = _safe_string(plan_source, "plan_source", "live_llm")
    demo_summary["crystal_export_mode"] = _safe_string(plan_source, "crystal_export_mode", "safe")
    demo_summary["crystal_demo_export_enabled"] = bool(plan_source.get("crystal_demo_export_enabled"))

    result = {
        "schema_version": EXECUTION_LOOP_REPORT_SCHEMA_VERSION,
        "run_summary": run_summary,
        "demo_summary": demo_summary,
        "plan_source": plan_source,
        "sequence_diagram_markdown": sequence_diagram_markdown,
        "what_this_demonstrates": _what_this_demonstrates_for_source(plan_source),
        "llm_planner_reply": {
            "trace_json_path": _safe_string(planner_dict.get("trace_write", {}), "trace_json_path")
            if isinstance(planner_dict.get("trace_write"), Mapping)
            else "",
            "trace_markdown_path": planner_trace_markdown_path or "",
            "run_plan": run_plan,
            "plan_as_text": _safe_string(run_plan, "plan_as_text"),
            "tool_hints": _tool_hints_from_run_plan(run_plan),
        },
        "tool_parse_report": parse_dict,
        "executable_plan": {
            "execution_mode": _safe_string(executable_plan_dict, "execution_mode"),
            "execution_allowed": bool(executable_plan_dict.get("execution_allowed")),
            "status": _safe_string(executable_plan_dict, "status"),
            "step_table": [
                {
                    "step_index": int(step.get("step_index", index)),
                    "tool_name": _safe_string(step, "tool_name"),
                    "status": _safe_string(step, "status"),
                    "placeholder_refs": _placeholder_refs(step),
                }
                for index, step in enumerate(_mapping_list(executable_plan_dict, "executable_steps"))
            ],
            "report": executable_plan_report_dict,
        },
        "tool_execution_log": execution_rows,
        "result_continuation_notes": result_notes,
        **({"recovery_attempt": to_json_dict(recovery_attempt)} if isinstance(recovery_attempt, Mapping) else {}),
        "final_outputs": final_outputs,
        "artifact_index": artifact_index,
    }
    assert_json_serializable(result)
    return result


def _display_value(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value
    if value is None:
        return "Not produced"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, Mapping):
        return json.dumps(to_json_dict(value), sort_keys=True)
    return str(value)


def _markdown_for_report(report: Mapping[str, Any]) -> str:
    report_dict = to_json_dict(report)
    run_summary = (
        to_json_dict(report_dict.get("run_summary", {}))
        if isinstance(report_dict.get("run_summary"), Mapping)
        else {}
    )
    demo_summary = (
        to_json_dict(report_dict.get("demo_summary", {}))
        if isinstance(report_dict.get("demo_summary"), Mapping)
        else {}
    )
    planner_reply = (
        to_json_dict(report_dict.get("llm_planner_reply", {}))
        if isinstance(report_dict.get("llm_planner_reply"), Mapping)
        else {}
    )
    parse_report = (
        to_json_dict(report_dict.get("tool_parse_report", {}))
        if isinstance(report_dict.get("tool_parse_report"), Mapping)
        else {}
    )
    executable_plan = (
        to_json_dict(report_dict.get("executable_plan", {}))
        if isinstance(report_dict.get("executable_plan"), Mapping)
        else {}
    )
    plan_source = (
        to_json_dict(report_dict.get("plan_source", {}))
        if isinstance(report_dict.get("plan_source"), Mapping)
        else {}
    )
    tool_execution_log = _mapping_list(report_dict, "tool_execution_log")
    result_notes = (
        to_json_dict(report_dict.get("result_continuation_notes", {}))
        if isinstance(report_dict.get("result_continuation_notes"), Mapping)
        else {}
    )
    recovery_attempt = (
        to_json_dict(report_dict.get("recovery_attempt", {}))
        if isinstance(report_dict.get("recovery_attempt"), Mapping)
        else {}
    )
    final_outputs = (
        to_json_dict(report_dict.get("final_outputs", {}))
        if isinstance(report_dict.get("final_outputs"), Mapping)
        else {}
    )
    artifact_index = _mapping_list(report_dict, "artifact_index")

    step_table_lines = [
        "| step index | tool | status | placeholder refs |",
        "| --- | --- | --- | --- |",
    ]
    for row in _mapping_list(executable_plan, "step_table"):
        placeholders = ", ".join(_string_list(row, "placeholder_refs")) or "-"
        step_table_lines.append(
            f"| {int(row.get('step_index', 0))} | {_safe_string(row, 'tool_name')} | {_safe_string(row, 'status')} | {placeholders} |"
        )

    tool_lines: list[str] = []
    for row in tool_execution_log:
        artifact_refs = _mapping_list(row, "artifact_refs")
        artifact_lines = (
            "\n".join(
                f"  - {_safe_string(ref, 'ref_name')}: {_safe_string(ref, 'value')}"
                for ref in artifact_refs
            )
            if artifact_refs
            else "  - None"
        )
        tool_lines.extend(
            [
                f"### Step {int(row.get('step_index', 0))}: {_safe_string(row, 'tool_name')}",
                f"- execution_performed: `{str(bool(row.get('execution_performed'))).lower()}`",
                f"- status: `{_safe_string(row, 'status')}`",
                f"- arguments: `{json.dumps(to_json_dict(row.get('arguments', {})) if isinstance(row.get('arguments'), Mapping) else {}, sort_keys=True)}`",
                f"- output summary: `{json.dumps(to_json_dict(row.get('output_summary', {})) if isinstance(row.get('output_summary'), Mapping) else {}, sort_keys=True)}`",
                "- important artifact refs:",
                artifact_lines,
                f"- error: `{json.dumps(to_json_dict(row.get('error')) if isinstance(row.get('error'), Mapping) else None, sort_keys=True)}`",
                f"- decision: `{_safe_string(row, 'decision')}`",
                "",
            ]
        )

    tool_hints = _string_list(planner_reply, "tool_hints")
    demonstration_lines = [
        f"- {line}" for line in _string_list(report_dict, "what_this_demonstrates")
    ] or ["- No demonstration summary was recorded."]
    planner_output_fallback = (
        "Not produced; deterministic showcase mode did not call the live planner."
        if bool(plan_source.get("deterministic_showcase"))
        else "Not separately written; raw output is stored in the planner trace JSON."
    )
    plan_origin_note = (
        "This deterministic showcase plan was not generated by a live LLM planner."
        if bool(plan_source.get("deterministic_showcase"))
        else "This plan came from the live LLM planner."
    )

    result_note_lines: list[str] = []
    if result_notes:
        for key in ("result_inspection", "failure_handling", "partial_success", "continuation_summary"):
            if isinstance(result_notes.get(key), Mapping):
                result_note_lines.extend(
                    [
                        f"### {key}",
                        "```json",
                        json.dumps(to_json_dict(result_notes[key]), indent=2, sort_keys=True),
                        "```",
                        "",
                    ]
                )
    else:
        result_note_lines.extend(
            [
                "- No result inspection, failure handling, or continuation artifacts were provided for this run.",
                "",
            ]
        )

    recovery_lines: list[str] = []
    if recovery_attempt:
        retry_validation = (
            to_json_dict(recovery_attempt.get("retry_validation", {}))
            if isinstance(recovery_attempt.get("retry_validation"), Mapping)
            else {}
        )
        solve_attempt = (
            to_json_dict(recovery_attempt.get("solve", {}))
            if isinstance(recovery_attempt.get("solve"), Mapping)
            else {}
        )
        recovery_lines.extend(
            [
                "## Recovery Attempt",
                f"- action: {_safe_string(recovery_attempt, 'action', 'Not produced')}",
                f"- status: {_safe_string(recovery_attempt, 'status', 'Not produced')}",
                f"- original errors: {_display_value(recovery_attempt.get('original_validation_errors'))}",
                f"- corrected request path: {_display_value(recovery_attempt.get('corrected_request_path'))}",
                f"- pot_root used: {_display_value(recovery_attempt.get('pot_root'))}",
                f"- removed guidance params: {_display_value(recovery_attempt.get('removed_guidance_params'))}",
                f"- retry validation status: {_display_value(retry_validation.get('status'))}",
                f"- retry validation valid: {_display_value(retry_validation.get('valid'))}",
                f"- retry validation errors: {_display_value(retry_validation.get('validation_errors'))}",
                f"- solve attempted: {_display_value(solve_attempt.get('attempted'))}",
                f"- solve status: {_display_value(solve_attempt.get('status'))}",
                f"- final status: {_display_value(recovery_attempt.get('final_status'))}",
                "",
            ]
        )

    artifact_lines = [
        f"- {_safe_string(item, 'label')}: {_safe_string(item, 'path')}"
        for item in artifact_index
    ] or ["- None"]

    lines = [
        "# Agentic Execution Loop Report",
        "",
        "## Demo Summary",
        f"- {_safe_string(demo_summary, 'status_sentence')}",
        f"- run id: {_safe_string(demo_summary, 'run_id', 'unknown')}",
        f"- status: {_safe_string(demo_summary, 'status')}",
        f"- execution performed: `{str(bool(demo_summary.get('execution_performed'))).lower()}`",
        f"- executed tool count: {int(demo_summary.get('executed_tool_count', 0))}",
        f"- blocked tool count: {int(demo_summary.get('blocked_tool_count', 0))}",
        f"- final solution/candidate status: {_safe_string(demo_summary, 'final_solution_candidate_status', 'Not produced')}",
        f"- final novelty status: {_safe_string(demo_summary, 'final_novelty_status', 'Not produced')}",
        f"- material/example: {_safe_string(demo_summary, 'material_or_example', 'Not specified')}",
        f"- backend: {_safe_string(demo_summary, 'backend', 'Not specified')}",
        f"- plan_source: {_safe_string(demo_summary, 'plan_source', 'live_llm')}",
        f"- crystal export mode: {_safe_string(demo_summary, 'crystal_export_mode', 'safe')}",
        f"- crystal demo export enabled: `{str(bool(demo_summary.get('crystal_demo_export_enabled'))).lower()}`",
        f"- workflow evaluation report: [workflow_evaluation.md](workflow_evaluation.md)",
        "",
        "## Plan Source",
        f"- plan_source: {_safe_string(plan_source, 'plan_source', 'live_llm')}",
        f"- live LLM used: `{str(bool(plan_source.get('live_llm_used'))).lower()}`",
        f"- deterministic showcase: `{str(bool(plan_source.get('deterministic_showcase'))).lower()}`",
        f"- crystal export mode: {_safe_string(plan_source, 'crystal_export_mode', 'safe')}",
        f"- crystal demo export enabled: `{str(bool(plan_source.get('crystal_demo_export_enabled'))).lower()}`",
        f"- warning: {_safe_string(plan_source, 'warning') or 'None'}",
        "",
        "## Sequence Diagram",
        report_dict.get("sequence_diagram_markdown", "").rstrip(),
        "",
        "## What This Demonstrates",
        *demonstration_lines,
        "",
        "## LLM Plan",
        f"- raw planner output path if available: {_safe_string(planner_reply, 'trace_json_path') or planner_output_fallback}",
        f"- planner trace markdown if available: {_safe_string(planner_reply, 'trace_markdown_path') or 'Not produced'}",
        f"- plan origin note: {plan_origin_note}",
        "- parsed RunPlan:",
        "```json",
        json.dumps(
            to_json_dict(planner_reply.get("run_plan", {}))
            if isinstance(planner_reply.get("run_plan"), Mapping)
            else {},
            indent=2,
            sort_keys=True,
        ),
        "```",
        "- plan_as_text:",
        "```text",
        _safe_string(planner_reply, "plan_as_text"),
        "```",
        f"- extracted tool_hint lines: {', '.join(tool_hints) or 'None'}",
        "",
        "## Parsed Tools",
        f"- proposal_count: {int(parse_report.get('proposal_count', 0))}",
        f"- valid_count: {int(parse_report.get('valid_count', 0))}",
        f"- invalid_count: {int(parse_report.get('invalid_count', 0))}",
        f"- ordered tool sequence: {', '.join(_string_list(parse_report, 'tool_sequence')) or 'None'}",
        f"- warnings: {', '.join(_string_list(parse_report, 'warnings')) or 'None'}",
        "",
        "## Executable Plan",
        f"- execution_mode: {_safe_string(executable_plan, 'execution_mode')}",
        f"- execution_allowed: `{str(bool(executable_plan.get('execution_allowed'))).lower()}`",
        f"- status: {_safe_string(executable_plan, 'status')}",
        "",
        *step_table_lines,
        "",
        "## Executed Tools and Outputs",
        "",
        *tool_lines,
        "## Final Outputs",
        f"- candidate CIF path: {_display_value(final_outputs.get('candidate_cif_path'))}",
        f"- solution CIF path: {_display_value(final_outputs.get('solution_cif_path'))}",
        f"- SPP output: {_display_value(final_outputs.get('spp_output'))}",
        f"- SPP package/ref: {_display_value(final_outputs.get('spp_package_ref'))}",
        f"- SPP bundle path: {_display_value(final_outputs.get('spp_bundle_path'))}",
        f"- QLIP package emitted by SPP: {_display_value(final_outputs.get('spp_qlip_package'))}",
        f"- compatibility status: {_display_value(final_outputs.get('spp_qlip_package_status'))}",
        f"- qlip solve compatible: {_display_value(final_outputs.get('spp_qlip_solve_compatible'))}",
        f"- SPP POT root: {_display_value(final_outputs.get('spp_pot_root'))}",
        f"- required POT pairs: {_display_value(final_outputs.get('spp_qlip_required_pairs'))}",
        f"- missing POT pairs: {_display_value(final_outputs.get('spp_qlip_missing_pairs'))}",
        f"- missing requirements: {_display_value(final_outputs.get('spp_qlip_package_missing'))}",
        f"- SPP corpus quality: {_display_value(final_outputs.get('spp_corpus_quality_status'))}",
        f"- SPP corpus quality diagnostics: {_display_value(final_outputs.get('spp_corpus_quality'))}",
        f"- SPP packaging errors: {_display_value(final_outputs.get('spp_qlip_package_errors'))}",
        f"- QLIP request/ref: {_display_value(final_outputs.get('request_ref'))}",
        f"- validated request/ref: {_display_value(final_outputs.get('validated_request_ref'))}",
        f"- QLIP packaging/validation status: {_display_value(final_outputs.get('qlip_packaging_validation_status'))}",
        f"- validation status: {_display_value(final_outputs.get('qlip_validation_status'))}",
        f"- validation errors: {_display_value(final_outputs.get('qlip_validation_errors'))}",
        f"- solve attempted: {_display_value(final_outputs.get('qlip_solve_attempted'))}",
        f"- proposed recovery action: {_display_value(final_outputs.get('proposed_recovery_action'))}",
        f"- recovery reason: {_display_value(final_outputs.get('recovery_reason'))}",
        f"- recovery next step hint: {_display_value(final_outputs.get('recovery_next_step_hint'))}",
        f"- novelty result/is_novel: {_display_value(final_outputs.get('novelty_result'))}",
        f"- final QLIP status: {_display_value(final_outputs.get('final_qlip_status'))}",
        f"- final objective value: {_display_value(final_outputs.get('final_objective_value'))}",
        f"- any final status: {_display_value(run_summary.get('status'))}",
        "",
        *recovery_lines,
        "### Result / Continuation Notes",
        "",
        *result_note_lines,
        "## Artifact Index",
        *artifact_lines,
        "",
    ]
    return "\n".join(lines)


def _tool_trace_markdown(
    report: Mapping[str, Any],
    planner_trace: Mapping[str, Any] | None,
    planner_trace_json_path: str | None,
) -> str:
    sections: list[str] = []
    if isinstance(planner_trace, Mapping):
        sections.append(render_agentic_llm_trace_markdown(planner_trace, "planner").rstrip())
    else:
        sections.extend(
            [
                "# Agentic LLM + Tool Trace",
                "",
                "## Planner Trace",
                "",
                f"- Planner trace JSON: {planner_trace_json_path or 'Unavailable'}",
                "",
            ]
        )

    report_dict = to_json_dict(report)
    sections.extend(
        [
            "",
            "## Tool Execution Trace",
            "",
        ]
    )
    for row in _mapping_list(report_dict, "tool_execution_log"):
        sections.extend(
            [
                f"### Step {int(row.get('step_index', 0))}: {_safe_string(row, 'tool_name')}",
                f"- status: `{_safe_string(row, 'status')}`",
                f"- execution_performed: `{str(bool(row.get('execution_performed'))).lower()}`",
                f"- decision: `{_safe_string(row, 'decision')}`",
                "```json",
                json.dumps(row, indent=2, sort_keys=True),
                "```",
                "",
            ]
        )
    return "\n".join(sections).strip() + "\n"


def write_execution_loop_report(
    report: Mapping[str, Any],
    out_dir: str | Path,
    *,
    planner_trace: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report_dict = to_json_dict(report)
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)

    report_json_path = root / "execution_loop_report.json"
    report_md_path = root / "execution_loop_report.md"
    llm_tool_trace_md_path = root / "llm_and_tool_trace.md"

    artifact_index = _mapping_list(report_dict, "artifact_index")
    augmented_index = list(artifact_index)
    augmented_index.extend(
        [
            {"label": "Execution loop report JSON", "path": str(report_json_path)},
            {"label": "Execution loop report Markdown", "path": str(report_md_path)},
            {"label": "LLM + tool trace Markdown", "path": str(llm_tool_trace_md_path)},
        ]
    )
    report_to_write = dict(report_dict)
    report_to_write["artifact_index"] = augmented_index

    planner_reply = report_to_write.get("llm_planner_reply")
    planner_trace_json_path = (
        _safe_string(planner_reply, "trace_json_path")
        if isinstance(planner_reply, Mapping)
        else ""
    )

    _write_json(report_json_path, report_to_write)
    _write_text(report_md_path, _markdown_for_report(report_to_write))
    _write_text(
        llm_tool_trace_md_path,
        _tool_trace_markdown(report_to_write, planner_trace, planner_trace_json_path),
    )

    result = {
        "schema_version": EXECUTION_LOOP_REPORT_WRITE_SCHEMA_VERSION,
        "report_json_path": str(report_json_path),
        "report_markdown_path": str(report_md_path),
        "llm_and_tool_trace_markdown_path": str(llm_tool_trace_md_path),
        "artifact_paths": [
            str(report_json_path),
            str(report_md_path),
            str(llm_tool_trace_md_path),
        ],
    }
    assert_json_serializable(result)
    return result


__all__ = [
    "EXECUTION_LOOP_REPORT_SCHEMA_VERSION",
    "EXECUTION_LOOP_REPORT_WRITE_SCHEMA_VERSION",
    "build_execution_loop_report",
    "write_execution_loop_report",
]
