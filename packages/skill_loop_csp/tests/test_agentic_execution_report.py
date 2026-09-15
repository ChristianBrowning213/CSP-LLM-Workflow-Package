from __future__ import annotations

import ast
import inspect
import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from sok_llm_orchestrator.agentic.execution_report import (
    EXECUTION_LOOP_REPORT_SCHEMA_VERSION,
    build_execution_loop_report,
    write_execution_loop_report,
)
from sok_llm_orchestrator.agentic.plan_compile import build_tool_parse_report, compile_run_plan_to_tool_proposals
from sok_llm_orchestrator.agentic.execution_plan_adapter import (
    build_executable_plan_from_compile_result,
    build_executable_plan_report,
)
import sok_llm_orchestrator.agentic.execution_report as execution_report_module


@contextmanager
def _local_test_dir(name: str):
    root = Path.cwd() / "test_workdir" / "agentic_exec_tests"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)


def _planner_compile_run(trace_path: Path) -> dict[str, object]:
    compile_result = compile_run_plan_to_tool_proposals(
        {
            "schema_version": "agentic_csp.run_plan.v1",
            "run_id": "run_001",
            "overall_goal": "TiO2",
            "plan_as_text": "\n".join(
                [
                    "1. Retrieve candidates.",
                    "tool_hint: crystal.csp_pack",
                    "tool_hint: spp.run_pipeline",
                ]
            ),
        }
    )
    return {
        "schema_version": "agentic_csp.planner_compile_run.v1",
        "run_plan": {
            "schema_version": "agentic_csp.run_plan.v1",
            "run_id": "run_001",
            "overall_goal": "TiO2",
            "run_goal": "demo loop",
            "stage": "wide_exploration",
            "detailed_description": "Demo planner reply.",
            "hoping_to_find": "A sequence to inspect.",
            "plan_as_text": "1. Retrieve candidates.\ntool_hint: crystal.csp_pack\ntool_hint: spp.run_pipeline",
            "what_we_tried_previously_that_is_related": "Nothing yet.",
            "success_criteria": "Readable loop",
            "stop_conditions_for_this_run": "Planner invalid",
        },
        "compile_result": compile_result,
        "proposal_count": len(compile_result["proposals"]),
        "valid_proposal_count": sum(1 for item in compile_result["validation_results"] if item["valid"] is True),
        "invalid_proposal_count": sum(1 for item in compile_result["validation_results"] if item["valid"] is False),
        "warnings": compile_result["warnings"],
        "trace_write": {"trace_json_path": str(trace_path)},
        "plan_source": "deterministic_showcase",
        "material_system": "CoAs2",
        "mcp_backend": "fake",
        "live_llm_used": False,
        "crystal_export_mode": "safe",
        "crystal_demo_export_enabled": False,
    }


def _planner_trace() -> dict[str, object]:
    return {
        "agent_name": "planner",
        "system_prompt": "Return JSON only.",
        "user_payload": {"run_goal": "demo loop"},
        "raw_output": "{\"schema_version\":\"agentic_csp.run_plan.v1\"}",
        "parsed_output": {
            "schema_version": "agentic_csp.run_plan.v1",
            "overall_goal": "TiO2",
            "run_goal": "demo loop",
        },
        "validation_errors": [],
        "attempts": [{"attempt_number": 1, "validation_errors": []}],
        "runtime_context": {"model": "test-model", "base_url": "http://localhost"},
    }


def _execution_run() -> dict[str, object]:
    return {
        "schema_version": "agentic_csp.execution_run.v1",
        "status": "partial",
        "execution_performed": True,
        "executed_tool_sequence": ["crystal.csp_pack", "qlip.validate_request"],
        "blocked_tool_sequence": ["qlip.solve"],
        "step_results": [
            {
                "step_index": 0,
                "tool_name": "crystal.csp_pack",
                "arguments": {"case_id": "run_001", "objective_family": "TiO2"},
                "execution_performed": True,
                "status": "succeeded",
                "output_summary": {"exported_cif_count": 1},
                "artifact_refs": [
                    {"ref_name": "corpus_ref", "value": "C:\\demo\\cifs", "kind": "directory"},
                    {"ref_name": "candidate_cif_path", "value": "C:\\demo\\candidate.cif", "kind": "file"},
                ],
                "raw_result_ref": "C:\\demo\\step_000\\raw_tool_response.json",
                "error": None,
            },
            {
                "step_index": 1,
                "tool_name": "qlip.validate_request",
                "arguments": {"case_id": "run_001", "request_ref": "C:\\demo\\request.json"},
                "execution_performed": True,
                "status": "succeeded",
                "output_summary": {
                    "valid": False,
                    "validation_errors": [
                        {
                            "code": "pot_root_missing",
                            "message": "missing potential root",
                            "path": "/context/pot_root",
                        }
                    ],
                },
                "artifact_refs": [
                    {"ref_name": "request_ref", "value": "C:\\demo\\request.json", "kind": "file"},
                    {"ref_name": "validated_request_ref", "value": "C:\\demo\\validated_request.json", "kind": "file"},
                ],
                "raw_result_ref": "C:\\demo\\step_001\\raw_tool_response.json",
                "error": None,
            },
            {
                "step_index": 2,
                "tool_name": "qlip.solve",
                "arguments": {"case_id": "run_001", "validated_request_ref": "C:\\demo\\validated_request.json"},
                "execution_performed": False,
                "status": "blocked",
                "output_summary": {},
                "artifact_refs": [],
                "raw_result_ref": None,
                "error": {"code": "qlip_request_invalid", "message": "validation failed"},
            },
        ],
        "stopped_reason": "qlip_request_invalid",
        "artifact_paths": {
            "execution_run_json": "C:\\demo\\execution_run.json",
            "execution_step_log_jsonl": "C:\\demo\\execution_step_log.jsonl",
        },
        "warnings": [],
    }


def test_execution_report_writes_json_markdown_and_tool_trace() -> None:
    with _local_test_dir("execution_report") as workdir:
        trace_path = workdir / "planner" / "agentic_llm_trace_planner.json"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_payload = _planner_trace()
        trace_path.write_text(json.dumps(trace_payload, indent=2), encoding="utf-8")

        planner_compile_run = _planner_compile_run(trace_path)
        parse_report = build_tool_parse_report(planner_compile_run["compile_result"], route_mode="demo")
        executable_plan = build_executable_plan_from_compile_result(planner_compile_run["compile_result"])
        executable_plan_report = build_executable_plan_report(executable_plan)
        step_rows = [
            {
                "step_index": 0,
                "tool_name": "crystal.csp_pack",
                "arguments": {"case_id": "run_001", "objective_family": "TiO2"},
                "execution_performed": True,
                "status": "succeeded",
                "output_summary": {"exported_cif_count": 1},
                "artifact_refs": [
                    {"ref_name": "corpus_ref", "value": "C:\\demo\\cifs", "kind": "directory"},
                    {"ref_name": "candidate_cif_path", "value": "C:\\demo\\candidate.cif", "kind": "file"},
                ],
                "error": None,
                "decision": "continue",
            },
            {
                "step_index": 1,
                "tool_name": "qlip.validate_request",
                "arguments": {"case_id": "run_001", "request_ref": "C:\\demo\\request.json"},
                "execution_performed": True,
                "status": "succeeded",
                "output_summary": {
                    "valid": False,
                    "validation_errors": [
                        {
                            "code": "pot_root_missing",
                            "message": "missing potential root",
                            "path": "/context/pot_root",
                        }
                    ],
                },
                "artifact_refs": [
                    {"ref_name": "request_ref", "value": "C:\\demo\\request.json", "kind": "file"},
                    {"ref_name": "validated_request_ref", "value": "C:\\demo\\validated_request.json", "kind": "file"},
                ],
                "error": None,
                "decision": "continue",
            },
            {
                "step_index": 2,
                "tool_name": "qlip.solve",
                "arguments": {"case_id": "run_001", "validated_request_ref": "C:\\demo\\validated_request.json"},
                "execution_performed": False,
                "status": "blocked",
                "output_summary": {},
                "artifact_refs": [],
                "error": {"code": "qlip_request_invalid", "message": "validation failed"},
                "decision": "blocked",
            },
        ]

        report = build_execution_loop_report(
            planner_compile_run=planner_compile_run,
            parse_report=parse_report,
            executable_plan=executable_plan,
            executable_plan_report=executable_plan_report,
            execution_run=_execution_run(),
            tool_execution_rows=step_rows,
            result_inspection={
                "schema_version": "agentic_csp.result_inspection.v1",
                "status": "recovery_recommended",
                "inspected_steps": [
                    {
                        "step_index": 1,
                        "tool_name": "qlip.validate_request",
                        "input_status": "succeeded",
                        "inspection_status": "recovery_recommended",
                        "detected_issue": "pot_root_missing",
                        "recommended_action": "repackage_qlip_request",
                        "recovery_reason": "missing_or_invalid_qlip_packaging_inputs",
                    }
                ],
                "blocked_reasons": [],
                "recovery_recommendations": ["qlip.validate_request: repackage_qlip_request"],
                "warnings": [],
            },
            failure_handling={
                "schema_version": "agentic_csp.failure_handling.v1",
                "status": "recovery_planned",
                "actions": [
                    {
                        "action_index": 0,
                        "source_step_index": 1,
                        "tool_name": "qlip.validate_request",
                        "detected_issue": "pot_root_missing",
                        "action_type": "repackage_qlip_request",
                        "reason": "QLIP packaging or validation diagnostics require rebuilding the request.",
                        "recovery_reason": "missing_or_invalid_qlip_packaging_inputs",
                        "next_step_hint": "Rebuild QLIP request from SPP bundle with valid pot_root/guidance params before solving.",
                    }
                ],
                "blocked_reasons": [],
                "recovery_actions": ["repackage_qlip_request"],
                "warnings": [],
            },
            partial_success={
                "schema_version": "agentic_csp.partial_success.v1",
                "route_mode": "demo_execution_loop",
                "source_run_id": "run_001",
                "status": "continue_with_warnings",
                "continuation_plan": [
                    {
                        "step_index": 1,
                        "tool_name": "qlip.validate_request",
                        "continuation_decision": "recovery_required",
                        "reason": "QLIP packaging or validation diagnostics require rebuilding the request.",
                    }
                ],
                "blocked_dependencies": [],
                "optional_stages_skipped": [],
                "recovery_paths": ["qlip.validate_request"],
                "warnings": ["Recovery paths required for: qlip.validate_request"],
            },
            continuation_summary={
                "schema_version": "agentic_csp.continuation_summary.v1",
                "final_status": "continue_with_warnings",
                "continued_steps": [],
                "skipped_steps": [],
                "blocked_steps": [],
                "recovery_steps": ["qlip.validate_request"],
                "summary_text": "Continuation allowed with warnings: recovery required: qlip.validate_request.",
            },
            recovery_attempt={
                "schema_version": "agentic_csp.qlip_recovery_attempt.v1",
                "action": "repackage_qlip_request",
                "status": "retry_invalid",
                "original_validation_errors": [
                    {
                        "code": "pot_root_missing",
                        "message": "missing potential root",
                        "path": "/context/pot_root",
                    }
                ],
                "corrected_request_path": "C:\\demo\\recovery\\corrected_qlip_request.json",
                "pot_root": "C:\\demo\\bundle\\spp_root",
                "removed_guidance_params": ["spp_package_path", "top_k_breakdown"],
                "warnings": [],
                "blocked_reason": None,
                "retry_validation": {
                    "attempted": True,
                    "status": "succeeded",
                    "valid": False,
                    "validation_errors": [
                        {
                            "code": "pot_root_missing",
                            "message": "missing potential root",
                            "path": "/context/pot_root",
                        }
                    ],
                    "validated_request_ref": "C:\\demo\\recovery\\retry_validated_request.json",
                    "raw_validation_response_ref": "C:\\demo\\recovery\\retry_raw_validation_response.json",
                },
                "solve": {
                    "attempted": False,
                    "status": "not_attempted",
                    "solution_cif_path": None,
                    "raw_solve_response_ref": None,
                    "error": None,
                },
                "novelty": {
                    "attempted": False,
                    "status": "not_attempted",
                    "is_novel": None,
                    "raw_novelty_response_ref": None,
                    "error": None,
                },
                "recovery_step_log_path": "C:\\demo\\recovery\\recovery_step_log.jsonl",
                "final_status": "retry_invalid",
            },
            parse_report_path=str(workdir / "plan" / "tool_parse_report.json"),
            executable_plan_path=str(workdir / "plan" / "executable_plan.json"),
            executable_plan_report_path=str(workdir / "plan" / "executable_plan_report.json"),
        )
        write_result = write_execution_loop_report(report, workdir / "report", planner_trace=trace_payload)

        assert report["schema_version"] == EXECUTION_LOOP_REPORT_SCHEMA_VERSION
        assert Path(write_result["report_json_path"]).exists()
        assert Path(write_result["report_markdown_path"]).exists()
        assert Path(write_result["llm_and_tool_trace_markdown_path"]).exists()

        markdown = Path(write_result["report_markdown_path"]).read_text(encoding="utf-8")
        assert "# Agentic Execution Loop Report" in markdown
        assert "## Demo Summary" in markdown
        assert "## Plan Source" in markdown
        assert "## Sequence Diagram" in markdown
        assert "## What This Demonstrates" in markdown
        assert "## LLM Plan" in markdown
        assert "## Parsed Tools" in markdown
        assert "## Executable Plan" in markdown
        assert "## Executed Tools and Outputs" in markdown
        assert "## Final Outputs" in markdown
        assert "No old hardcoded pipeline shortcut was used." in markdown
        assert "workflow_evaluation.md" in markdown
        assert "plan_source: deterministic_showcase" in markdown
        assert "live LLM used: `false`" in markdown
        assert "deterministic showcase: `true`" in markdown
        assert "crystal export mode: safe" in markdown
        assert "crystal demo export enabled: `false`" in markdown
        assert "Fake MCP backend is in use for this demo run." in markdown
        assert "This deterministic showcase plan was not generated by a live LLM planner." in markdown
        assert "crystal.csp_pack" in markdown
        assert "qlip.validate_request" in markdown
        assert "qlip.solve" in markdown
        assert "execution_step_log.jsonl" in markdown
        assert "candidate CIF path: C:\\demo\\candidate.cif" in markdown
        assert "solution CIF path: Not produced" in markdown
        assert "validation status: invalid" in markdown
        assert "QLIP packaging/validation status: invalid" in markdown
        assert "pot_root_missing" in markdown
        assert "proposed recovery action: repackage_qlip_request" in markdown
        assert "missing_or_invalid_qlip_packaging_inputs" in markdown
        assert "## Recovery Attempt" in markdown
        assert "corrected request path: C:\\demo\\recovery\\corrected_qlip_request.json" in markdown
        assert "retry validation valid: false" in markdown
        assert "solve attempted: false" in markdown


def test_execution_report_has_no_pipeline_or_sqlite_dependency() -> None:
    source = inspect.getsource(execution_report_module)
    tree = ast.parse(source)
    imported_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module.split(".")[0])

    assert "sqlite3" not in imported_modules
    assert "sqlalchemy" not in imported_modules
    assert "pipeline" not in imported_modules
