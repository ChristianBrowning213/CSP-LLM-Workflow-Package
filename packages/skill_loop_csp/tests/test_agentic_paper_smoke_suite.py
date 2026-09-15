from __future__ import annotations

import ast
import inspect
import json
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from sok_llm_orchestrator.agentic.paper_smoke_suite import run_paper_smoke_suite
import sok_llm_orchestrator.agentic.paper_smoke_suite as paper_smoke_suite_module


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


def _suite_json(path: Path) -> Path:
    payload = {
        "schema_version": "skill_loop.smoke_suite.v1",
        "suite_name": "unit_suite",
        "runs": [
            {
                "id": "complete_case",
                "material_system": "CoAs2",
                "goal": "Generate CoAs2.",
                "expected_outcome": "completed",
                "expected_min_overall_score": 90,
            },
            {
                "id": "partial_case",
                "material_system": "ZnS",
                "goal": "Attempt ZnS.",
                "expected_outcome": "blocked_or_partial",
                "expected_error_codes": ["spp_request_ref_unavailable"],
                "expected_failure_family": "missing_pot_or_request_ref",
            },
        ],
    }
    suite_path = path / "suite.json"
    suite_path.write_text(json.dumps(payload), encoding="utf-8")
    return suite_path


def _fake_bundle(run_dir: Path, *, final_status: str, score: int, failed_tool: str = "", failure_code: str = "") -> dict[str, str]:
    report_dir = run_dir / "report"
    execution_dir = run_dir / "_raw_run" / "execution"
    report_dir.mkdir(parents=True, exist_ok=True)
    execution_dir.mkdir(parents=True, exist_ok=True)
    steps = [
        {"tool_name": "crystal.csp_pack", "status": "succeeded", "output_summary": {}, "artifact_refs": []},
        {"tool_name": "spp.run_pipeline", "status": "succeeded", "output_summary": {}, "artifact_refs": []},
    ]
    if final_status == "completed":
        solution = run_dir / "_raw_run" / "execution" / "solution.cif"
        solution.write_text("data_solution\n", encoding="utf-8")
        steps.extend(
            [
                {"tool_name": "qlip.validate_request", "status": "succeeded", "output_summary": {"valid": True}, "artifact_refs": []},
                {
                    "tool_name": "qlip.solve",
                    "status": "succeeded",
                    "output_summary": {"status": "OPTIMAL", "solution_cif_path": str(solution)},
                    "artifact_refs": [{"ref_name": "solution_cif_path", "value": str(solution), "kind": "file"}],
                },
                {"tool_name": "crystal.novelty_check", "status": "succeeded", "output_summary": {"is_novel": True}, "artifact_refs": []},
            ]
        )
    else:
        steps.append(
            {
                "tool_name": failed_tool or "qlip.validate_request",
                "status": "blocked",
                "output_summary": {},
                "artifact_refs": [],
                "error": {"code": failure_code or "spp_request_ref_unavailable", "message": "blocked"},
            }
        )
    (execution_dir / "execution_run.json").write_text(
        json.dumps({"status": final_status, "step_results": steps}, indent=2),
        encoding="utf-8",
    )
    evaluation = {
        "schema_version": "agentic_csp.workflow_evaluation.v1",
        "final_status": final_status,
        "scores": {
            "overall_score_0_100": score,
            "solve_quality_score_0_100": 100 if final_status == "completed" else 0,
            "novelty_score_0_100": 90 if final_status == "completed" else None,
        },
    }
    (report_dir / "workflow_evaluation.json").write_text(json.dumps(evaluation, indent=2), encoding="utf-8")
    (report_dir / "workflow_evaluation.md").write_text("# Workflow Evaluation Report\n", encoding="utf-8")
    (report_dir / "execution_loop_report.md").write_text("# Execution Loop Report\n", encoding="utf-8")
    return {
        "bundle_root": str(run_dir),
        "workflow_evaluation_json_path": str(report_dir / "workflow_evaluation.json"),
        "workflow_evaluation_markdown_path": str(report_dir / "workflow_evaluation.md"),
        "report_markdown_path": str(report_dir / "execution_loop_report.md"),
        "execution_loop_report_markdown_path": str(report_dir / "execution_loop_report.md"),
    }


def test_paper_smoke_suite_writes_summary_and_marks_expected_outcomes() -> None:
    with _local_test_dir("paper_smoke_suite") as workdir:
        suite_path = _suite_json(workdir)

        def fake_runner(item, run_dir):  # noqa: ANN001
            if item["id"] == "complete_case":
                return _fake_bundle(run_dir, final_status="completed", score=95)
            return _fake_bundle(
                run_dir,
                final_status="partial",
                score=48,
                failed_tool="qlip.validate_request",
                failure_code="spp_request_ref_unavailable",
            )

        result = run_paper_smoke_suite(
            suite_json=suite_path,
            out_dir=workdir / "out",
            run_demo_case=fake_runner,
        )

        summary_path = Path(result["summary_json_path"])
        markdown_path = Path(result["summary_markdown_path"])
        assert summary_path.exists()
        assert markdown_path.exists()
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["pass_count"] == 2
        assert summary["fail_count"] == 0
        complete = next(row for row in summary["runs"] if row["run_id"] == "complete_case")
        partial = next(row for row in summary["runs"] if row["run_id"] == "partial_case")
        assert complete["expected_outcome_pass"] is True
        assert partial["expected_outcome_pass"] is True
        assert partial["expected_error_codes"] == ["spp_request_ref_unavailable"]
        assert partial["actual_failure_code"] == "spp_request_ref_unavailable"
        assert partial["expectation_result"] == "pass"
        assert complete["artifact_paths"]["workflow_evaluation_md"].endswith("workflow_evaluation.md")
        assert complete["artifact_paths"]["execution_loop_report_md"].endswith("execution_loop_report.md")
        assert "complete_case" in markdown_path.read_text(encoding="utf-8")
        assert "workflow_evaluation.md" in markdown_path.read_text(encoding="utf-8")


def test_paper_smoke_suite_marks_unexpected_partial_for_complete_as_fail() -> None:
    with _local_test_dir("paper_smoke_suite_fail") as workdir:
        suite_path = _suite_json(workdir)

        def fake_runner(item, run_dir):  # noqa: ANN001
            _ = item
            return _fake_bundle(run_dir, final_status="partial", score=48)

        result = run_paper_smoke_suite(
            suite_json=suite_path,
            out_dir=workdir / "out",
            run_demo_case=fake_runner,
        )

        summary = json.loads(Path(result["summary_json_path"]).read_text(encoding="utf-8"))
        complete = next(row for row in summary["runs"] if row["run_id"] == "complete_case")
        assert complete["expected_outcome_pass"] is False
        assert summary["fail_count"] == 1


def test_paper_smoke_suite_requires_expected_error_code_for_partial() -> None:
    with _local_test_dir("paper_smoke_suite_error_code") as workdir:
        payload = {
            "schema_version": "skill_loop.smoke_suite.v1",
            "suite_name": "unit_suite",
            "runs": [
                {
                    "id": "partial_case",
                    "material_system": "ZnS",
                    "goal": "Attempt ZnS.",
                    "expected_outcome": "blocked_or_partial",
                    "expected_error_codes": ["non_concrete_formula"],
                }
            ],
        }
        suite_path = workdir / "suite.json"
        suite_path.write_text(json.dumps(payload), encoding="utf-8")

        def fake_runner(item, run_dir):  # noqa: ANN001
            _ = item
            return _fake_bundle(
                run_dir,
                final_status="partial",
                score=48,
                failed_tool="qlip.validate_request",
                failure_code="spp_request_ref_unavailable",
            )

        result = run_paper_smoke_suite(
            suite_json=suite_path,
            out_dir=workdir / "out",
            run_demo_case=fake_runner,
        )

        summary = json.loads(Path(result["summary_json_path"]).read_text(encoding="utf-8"))
        row = summary["runs"][0]
        assert row["expected_outcome_pass"] is False
        assert row["expectation_result"] == "fail"


def test_paper_smoke_suite_has_no_pipeline_or_sqlite_dependency() -> None:
    source = inspect.getsource(paper_smoke_suite_module)
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
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
