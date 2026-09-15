from __future__ import annotations

import ast
import inspect
import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from sok_llm_orchestrator.agentic.evaluator import (
    WORKFLOW_EVALUATION_SCHEMA_VERSION,
    build_workflow_evaluation,
    write_workflow_evaluation,
)
import sok_llm_orchestrator.agentic.evaluator as evaluator_module


@contextmanager
def _local_test_dir(name: str):
    root = Path.cwd() / "test_workdir" / "agentic_exec_tests"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _write_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path)


def _base_report(workdir: Path, *, novelty: dict[str, object] | None = None, spp_blocked: bool = False) -> dict[str, object]:
    request = workdir / "qlip_request.json"
    validated = workdir / "validated_request.json"
    solution = workdir / "solution.cif"
    corpus = workdir / "corpus"
    corpus.mkdir()
    request_payload = {"problem": {"chemistry": {"formula": "CoAs2"}}, "guidance": [], "solver": {"name": "gurobi"}}
    _write_json(request, request_payload)
    _write_json(validated, request_payload)
    solution.write_text("_chemical_formula_sum 'Co As2'\n", encoding="utf-8")
    step_log = workdir / "execution_step_log.jsonl"
    execution_run = workdir / "execution_run.json"
    step_log.write_text("{}", encoding="utf-8")
    _write_json(execution_run, {"schema_version": "agentic_csp.execution_run.v1"})

    spp_status = "blocked" if spp_blocked else "succeeded"
    spp_executed = not spp_blocked
    steps: list[dict[str, object]] = [
        {
            "step_index": 0,
            "tool_name": "crystal.csp_pack",
            "execution_performed": True,
            "status": "succeeded",
            "output_summary": {"neighbor_count": 10, "exported_cif_count": 1},
            "artifact_refs": [{"ref_name": "corpus_ref", "value": str(corpus), "kind": "directory"}],
            "raw_result_ref": str(workdir / "raw_csp.json"),
        },
        {
            "step_index": 1,
            "tool_name": "spp.run_pipeline",
            "execution_performed": spp_executed,
            "status": spp_status,
            "output_summary": {
                "qlip_solve_compatible": not spp_blocked,
                "qlip_package_required_pairs": ["Co-As", "As-As"],
                "qlip_package_missing_pairs": ["Co-As"] if spp_blocked else [],
                "pot_root": str(workdir / "pot"),
                "final_bundle": str(workdir / "bundle"),
            },
            "artifact_refs": [],
            "raw_result_ref": str(workdir / "raw_spp.json"),
        },
        {
            "step_index": 2,
            "tool_name": "qlip.validate_request",
            "execution_performed": not spp_blocked,
            "status": "blocked" if spp_blocked else "succeeded",
            "output_summary": {"valid": not spp_blocked, "validation_error_codes": ["spp_blocked"] if spp_blocked else []},
            "artifact_refs": [{"ref_name": "validated_request_ref", "value": str(validated), "kind": "file"}],
            "raw_result_ref": str(workdir / "raw_validate.json"),
        },
        {
            "step_index": 3,
            "tool_name": "qlip.solve",
            "execution_performed": not spp_blocked,
            "status": "blocked" if spp_blocked else "succeeded",
            "output_summary": {"status": "OPTIMAL", "objective_value": -1.25} if not spp_blocked else {},
            "artifact_refs": [{"ref_name": "solution_cif_path", "value": str(solution), "kind": "file"}] if not spp_blocked else [],
            "raw_result_ref": str(workdir / "raw_solve.json"),
        },
    ]
    if novelty is not None:
        steps.append(
            {
                "step_index": 4,
                "tool_name": "crystal.novelty_check",
                "execution_performed": True,
                "status": "succeeded",
                "output_summary": novelty,
                "artifact_refs": [],
                "raw_result_ref": str(workdir / "raw_novelty.json"),
            }
        )

    for raw in ("raw_csp.json", "raw_spp.json", "raw_validate.json", "raw_solve.json", "raw_novelty.json"):
        _write_json(workdir / raw, {"ok": True})

    return {
        "schema_version": "agentic_csp.execution_loop_report.v1",
        "demo_summary": {"run_id": "run_001", "status": "completed" if not spp_blocked else "partial", "backend": "fake"},
        "plan_source": {"plan_source": "deterministic_showcase", "material_system": "CoAs2", "mcp_backend": "fake"},
        "llm_planner_reply": {
            "run_plan": {
                "run_id": "run_001",
                "overall_goal": "Generate a CoAs2 candidate structure using retrieved analogues.",
                "plan_as_text": "tool_hint: crystal.csp_pack\ntool_hint: spp.run_pipeline\ntool_hint: qlip.validate_request\ntool_hint: qlip.solve\ntool_hint: crystal.novelty_check",
            }
        },
        "tool_execution_log": steps,
        "final_outputs": {
            "solution_cif_path": str(solution) if not spp_blocked else None,
            "final_qlip_status": "OPTIMAL" if not spp_blocked else "not_attempted",
            "final_objective_value": -1.25 if not spp_blocked else None,
            "request_ref": str(request),
            "validated_request_ref": str(validated),
            "novelty_result": novelty,
        },
        "artifact_index": [
            {"label": "Execution run JSON", "path": str(execution_run)},
            {"label": "Execution step log JSONL", "path": str(step_log)},
            {"label": "qlip.solve raw result JSON", "path": str(workdir / "raw_solve.json")},
        ],
    }


def test_completed_run_writes_workflow_evaluation_json_and_markdown() -> None:
    with _local_test_dir("workflow_eval_complete") as workdir:
        report = _base_report(workdir, novelty={"is_novel": True, "similarity": 0.12})
        evaluation = build_workflow_evaluation(report, execution_loop_report_path=workdir / "execution_loop_report.md")
        write_result = write_workflow_evaluation(evaluation, workdir / "report")

        assert evaluation["schema_version"] == WORKFLOW_EVALUATION_SCHEMA_VERSION
        assert evaluation["final_status"] == "completed"
        assert evaluation["requirement_checks"]["composition_requirement"]["status"] == "pass"
        assert Path(write_result["evaluation_json_path"]).exists()
        markdown = Path(write_result["evaluation_markdown_path"]).read_text(encoding="utf-8")
        assert "# Workflow Evaluation Report" in markdown
        assert "## Score Summary" in markdown
        assert "## Limitations" in markdown


def test_partial_run_with_spp_blocked_reports_partial_and_missing_checks() -> None:
    with _local_test_dir("workflow_eval_partial") as workdir:
        evaluation = build_workflow_evaluation(_base_report(workdir, novelty=None, spp_blocked=True))

        assert evaluation["final_status"] == "partial"
        assert evaluation["requirement_checks"]["spp_guidance_requirement"]["status"] == "fail"
        assert evaluation["requirement_checks"]["solve_requirement"]["status"] == "fail"
        assert evaluation["scores"]["novelty_score_0_100"] is None


def test_non_novel_result_is_not_execution_failure() -> None:
    with _local_test_dir("workflow_eval_nonnovel") as workdir:
        evaluation = build_workflow_evaluation(_base_report(workdir, novelty={"is_novel": False, "similarity": 0.97, "nearest_match": "mp-demo"}))

        assert evaluation["final_status"] == "completed"
        assert evaluation["scores"]["rediscovery_flag"] is True
        assert evaluation["scores"]["execution_success_score_0_100"] == 100
        assert evaluation["scores"]["novelty_score_0_100"] == 20


def test_missing_novelty_is_unknown_without_fake_score() -> None:
    with _local_test_dir("workflow_eval_missing_novelty") as workdir:
        evaluation = build_workflow_evaluation(_base_report(workdir, novelty=None))

        assert evaluation["requirement_checks"]["novelty_requirement"]["status"] == "unknown"
        assert evaluation["scores"]["novelty_score_0_100"] is None


def test_evaluator_includes_failure_classification_and_recovery_recommendation() -> None:
    with _local_test_dir("workflow_eval_failure") as workdir:
        report = _base_report(workdir, novelty=None)
        report["tool_execution_log"][3]["status"] = "failed"
        report["tool_execution_log"][3]["artifact_refs"] = []
        report["tool_execution_log"][3]["output_summary"] = {}
        report["tool_execution_log"][3]["raw_result_summary"] = {"status": "ERROR"}
        report["tool_execution_log"][3]["error"] = {
            "code": "non_solution_status",
            "message": "qlip.solve returned status=ERROR",
        }
        report["final_outputs"]["solution_cif_path"] = None
        report["final_outputs"]["final_qlip_status"] = "ERROR"
        report["result_continuation_notes"] = {
            "failure_handling": {
                "actions": [
                    {
                        "source_step_index": 3,
                        "tool_name": "qlip.solve",
                        "detected_issue": "qlip_error",
                        "action_type": "revise_qlip_formulation",
                        "next_step_hint": "Revise the QLIP formulation before retrying solve.",
                        "recovery_plan": {
                            "recovery_recommended": True,
                            "action": "revise_qlip_formulation",
                            "can_auto_retry": False,
                            "requires_new_data": False,
                            "requires_formulation_change": True,
                            "hint": "Revise the QLIP formulation before retrying solve.",
                            "next_step_hint": "Revise the QLIP formulation before retrying solve.",
                            "evidence_path": "raw_solve.json",
                        },
                    }
                ]
            }
        }

        evaluation = build_workflow_evaluation(report)
        markdown_result = write_workflow_evaluation(evaluation, workdir / "report")
        markdown = Path(markdown_result["evaluation_markdown_path"]).read_text(encoding="utf-8")

        assert evaluation["failure_assessment"]["failed_tool"] == "qlip.solve"
        assert evaluation["failure_assessment"]["classification"] == "qlip_error"
        assert evaluation["failure_assessment"]["recovery_plan"]["can_auto_retry"] is False
        assert "Revise the QLIP formulation before retrying solve." in evaluation["recommended_next_actions"]
        assert "## Failure Diagnostics" in markdown
        assert "qlip_error" in markdown


def test_scores_are_deterministic_and_bounded() -> None:
    with _local_test_dir("workflow_eval_scores") as workdir:
        report = _base_report(workdir, novelty={"is_novel": True})
        first = build_workflow_evaluation(report)
        second = build_workflow_evaluation(report)

        assert first["scores"] == second["scores"]
        for key, value in first["scores"].items():
            if key == "rediscovery_flag" or value is None:
                continue
            assert 0 <= value <= 100


def test_evaluator_has_no_old_pipeline_or_sqlite_imports() -> None:
    source = inspect.getsource(evaluator_module)
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module.split(".")[0])

    assert "sqlite3" not in imported_modules
    assert "sqlalchemy" not in imported_modules
    assert "pipeline" not in imported_modules
