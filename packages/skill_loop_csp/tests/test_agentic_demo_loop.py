from __future__ import annotations

import ast
import inspect
import json
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from sok_llm_orchestrator.agentic.demo_loop import (
    DEFAULT_DEMO_ALLOWED_TOOLS,
    DEMO_EXECUTION_LOOP_SCHEMA_VERSION,
    SHOWCASE_DEFAULT_GOAL,
    _parser,
    build_showcase_six_tool_run_plan,
    build_demo_mcp_settings,
    run_demo_execution_loop,
)
from sok_llm_orchestrator.agentic.demo_bundle import write_demo_showcase_bundle
from sok_llm_orchestrator.agentic.execution_plan_adapter import build_executable_plan_from_compile_result
from sok_llm_orchestrator.agentic.plan_compile import compile_run_plan_to_tool_proposals
from sok_llm_orchestrator.agentic.tool_execution_adapters import get_default_tool_execution_adapters
from sok_llm_orchestrator.config import Settings
import sok_llm_orchestrator.agentic.demo_loop as demo_loop_module


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


def _fake_settings(workdir: Path) -> Settings:
    root = Path(__file__).resolve().parents[1]
    return Settings(
        workspace_root=workdir,
        crystaldb_mcp_cmd=[sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_crystaldb_server.py")],
        spp_mcp_cmd=[sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_spp_server.py")],
        qlip_mcp_cmd=[sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_qlip_server.py")],
        crystaldb_mcp_cwd=str(root),
        spp_mcp_cwd=str(root),
        qlip_mcp_cwd=str(root),
        crystaldb_policy_mode="demo",
        max_runtime_seconds=30,
    )


def _planner_trace(workdir: Path) -> Path:
    trace_path = workdir / "planner" / "agentic_llm_trace_planner.json"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(
        json.dumps(
            {
                "agent_name": "planner",
                "system_prompt": "Return JSON only.",
                "user_payload": {"run_goal": "demo loop"},
                "raw_output": "{\"schema_version\":\"agentic_csp.run_plan.v1\"}",
                "parsed_output": {"schema_version": "agentic_csp.run_plan.v1", "overall_goal": "TiO2"},
                "validation_errors": [],
                "attempts": [{"attempt_number": 1, "validation_errors": []}],
                "runtime_context": {"model": "test-model", "base_url": "http://localhost"},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return trace_path


def _planner_compile_run(workdir: Path) -> dict[str, object]:
    compile_result = compile_run_plan_to_tool_proposals(
        {
            "schema_version": "agentic_csp.run_plan.v1",
            "run_id": "run_001",
            "overall_goal": "TiO2",
            "run_goal": "demo execution loop",
            "stage": "wide_exploration",
            "plan_as_text": "\n".join(
                [
                    "tool_hint: crystal.csp_pack",
                    "tool_hint: spp.run_pipeline",
                    "tool_hint: qlip.validate_request",
                    "tool_hint: qlip.solve",
                    "tool_hint: crystal.novelty_check",
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
            "run_goal": "demo execution loop",
            "stage": "wide_exploration",
            "detailed_description": "Demo run.",
            "hoping_to_find": "A visible execution loop.",
            "plan_as_text": "\n".join(
                [
                    "tool_hint: crystal.csp_pack",
                    "tool_hint: spp.run_pipeline",
                    "tool_hint: qlip.validate_request",
                    "tool_hint: qlip.solve",
                    "tool_hint: crystal.novelty_check",
                ]
            ),
            "what_we_tried_previously_that_is_related": "None.",
            "success_criteria": "Artifacts written.",
            "stop_conditions_for_this_run": "Adapter failure.",
        },
        "compile_result": compile_result,
        "proposal_count": len(compile_result["proposals"]),
        "valid_proposal_count": sum(1 for item in compile_result["validation_results"] if item["valid"] is True),
        "invalid_proposal_count": sum(1 for item in compile_result["validation_results"] if item["valid"] is False),
        "warnings": compile_result["warnings"],
        "trace_write": {"trace_json_path": str(_planner_trace(workdir))},
    }


def _recovery_adapters(workdir: Path, *, pot_root_available: bool) -> dict[str, object]:
    def crystal_adapter(step, *, arguments, prior_step_results, step_dir):
        _ = step, arguments, prior_step_results
        corpus_dir = step_dir / "cifs"
        corpus_dir.mkdir(parents=True, exist_ok=True)
        candidate = corpus_dir / "candidate.cif"
        candidate.write_text("data_candidate\n", encoding="utf-8")
        return {
            "schema_version": "agentic_csp.tool_execution_result.v1",
            "tool_name": "crystal.csp_pack",
            "execution_performed": True,
            "status": "succeeded",
            "output_summary": {"neighbor_count": 1, "exported_cif_count": 1},
            "artifact_refs": [
                {"ref_name": "corpus_ref", "value": str(corpus_dir), "kind": "directory"},
                {"ref_name": "candidate_cif_path", "value": str(candidate), "kind": "file"},
            ],
            "raw_result_ref": None,
            "raw_result_summary": {},
            "error": None,
            "warnings": [],
        }

    def spp_run_adapter(step, *, arguments, prior_step_results, step_dir):
        _ = step, arguments, prior_step_results
        run_root = step_dir / "run_root"
        scaled_root = run_root / "scaled_spp"
        fit_root = run_root / "fit_spp"
        final_bundle = run_root / "final_bundle"
        run_root.mkdir(parents=True, exist_ok=True)
        scaled_root.mkdir(parents=True, exist_ok=True)
        fit_root.mkdir(parents=True, exist_ok=True)
        final_bundle.mkdir(parents=True, exist_ok=True)
        if pot_root_available:
            (scaled_root / "Co-Co.POT").write_text("0.1 1.0\n0.2 0.5\n", encoding="utf-8")
        request_path = step_dir / "qlip_request.json"
        request_path.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "problem": {
                        "chemistry": {"formula": "CoAs2"},
                        "design_space": {
                            "template": {
                                "lattice": {
                                    "a": 4.6,
                                    "b": 4.6,
                                    "c": 3.0,
                                    "alpha": 90.0,
                                    "beta": 90.0,
                                    "gamma": 90.0,
                                    "units": "angstrom",
                                }
                            },
                            "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 4}},
                        },
                    },
                    "constraints": [],
                    "guidance": [
                        {
                            "id": "objective.energy_spp",
                            "params": {
                                "spp_package_path": str(final_bundle),
                                "pairs_policy": "task_pairs",
                                "oob_policy": "max",
                                "missing_pair_policy": "max_global",
                                "top_k_breakdown": 10,
                            },
                        }
                    ],
                    "solver": {"name": "gurobi"},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "schema_version": "agentic_csp.tool_execution_result.v1",
            "tool_name": "spp.run_pipeline",
            "execution_performed": True,
            "status": "succeeded",
            "output_summary": {
                "cif_count": 1,
                "run_root": str(run_root),
                "fit_spp_root": str(fit_root),
                "scaled_spp_root": str(scaled_root),
                "final_bundle": str(final_bundle),
                "request_ref": str(request_path),
                "spp_bundle_path": str(final_bundle),
                "spp_guidance_package_path": str(run_root / "qlip_package" / "guidance_package"),
                "spp_qlip_package_json": str(run_root / "qlip_package" / "package.json"),
                "qlip_package_status": "partial",
                "qlip_solve_compatible": False,
                "qlip_package_missing": ["context.pot_root"],
                "qlip_package_errors": [],
            },
            "artifact_refs": [
                {"ref_name": "spp_package_ref", "value": str(run_root), "kind": "directory"},
                {"ref_name": "fit_spp_root", "value": str(fit_root), "kind": "directory"},
                {"ref_name": "scaled_spp_root", "value": str(scaled_root), "kind": "directory"},
                {"ref_name": "spp_final_bundle_path", "value": str(final_bundle), "kind": "directory"},
                {"ref_name": "spp_bundle_path", "value": str(final_bundle), "kind": "directory"},
                {"ref_name": "request_ref", "value": str(request_path), "kind": "file"},
            ],
            "raw_result_ref": None,
            "raw_result_summary": {},
            "error": None,
            "warnings": [],
        }

    def spp_package_adapter(step, *, arguments, prior_step_results, step_dir):
        _ = step, arguments, prior_step_results
        bundle_root = step_dir / "bundle"
        bundle_spp_root = bundle_root / "spp_root"
        bundle_spp_root.mkdir(parents=True, exist_ok=True)
        if pot_root_available:
            (bundle_spp_root / "Co-Co.POT").write_text("0.1 1.0\n0.2 0.5\n", encoding="utf-8")
        request_path = step_dir / "qlip_request.json"
        request_path.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "problem": {
                        "chemistry": {"formula": "CoAs2"},
                        "design_space": {
                            "template": {
                                "lattice": {
                                    "a": 4.6,
                                    "b": 4.6,
                                    "c": 3.0,
                                    "alpha": 90.0,
                                    "beta": 90.0,
                                    "gamma": 90.0,
                                    "units": "angstrom",
                                }
                            },
                            "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 4}},
                        },
                    },
                    "constraints": [],
                    "guidance": [
                        {
                            "id": "objective.energy_spp",
                            "params": {
                                "spp_package_path": str(bundle_root),
                                "pairs_policy": "task_pairs",
                                "oob_policy": "max",
                                "missing_pair_policy": "max_global",
                                "top_k_breakdown": 10,
                            },
                        }
                    ],
                    "solver": {"name": "gurobi"},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "schema_version": "agentic_csp.tool_execution_result.v1",
            "tool_name": "spp.package_for_qlip",
            "execution_performed": True,
            "status": "succeeded",
            "output_summary": {"request_ref": str(request_path), "spp_bundle_path": str(bundle_root)},
            "artifact_refs": [
                {"ref_name": "request_ref", "value": str(request_path), "kind": "file"},
                {"ref_name": "spp_bundle_path", "value": str(bundle_root), "kind": "directory"},
            ],
            "raw_result_ref": None,
            "raw_result_summary": {},
            "error": None,
            "warnings": [],
        }

    def validate_adapter(step, *, arguments, prior_step_results, step_dir):
        _ = step, prior_step_results
        request_path = Path(arguments["request_ref"])
        request_payload = json.loads(request_path.read_text(encoding="utf-8"))
        params = request_payload.get("guidance", [{}])[0].get("params", {})
        pot_root = request_payload.get("context", {}).get("pot_root")
        valid = bool(pot_root) and params == {}
        validated_path = step_dir / "validated_request.json"
        validated_path.parent.mkdir(parents=True, exist_ok=True)
        validated_path.write_text(json.dumps(request_payload, indent=2), encoding="utf-8")
        errors = [] if valid else [{"code": "pot_root_missing", "message": "missing potential root", "path": "/context/pot_root"}]
        return {
            "schema_version": "agentic_csp.tool_execution_result.v1",
            "tool_name": "qlip.validate_request",
            "execution_performed": True,
            "status": "succeeded",
            "output_summary": {
                "valid": valid,
                "package_valid": valid,
                "package_validation_status": "valid" if valid else "invalid",
                "validation_errors": errors,
                "validation_error_codes": [item["code"] for item in errors],
                "capabilities": {"pot_root_resolved": valid},
            },
            "artifact_refs": [{"ref_name": "validated_request_ref", "value": str(validated_path), "kind": "file"}],
            "raw_result_ref": None,
            "raw_result_summary": {"valid": valid},
            "error": None,
            "warnings": [],
        }

    def solve_adapter(step, *, arguments, prior_step_results, step_dir):
        _ = step, arguments, prior_step_results
        solution = step_dir / "solution.cif"
        solution.parent.mkdir(parents=True, exist_ok=True)
        solution.write_text("data_solution\n", encoding="utf-8")
        return {
            "schema_version": "agentic_csp.tool_execution_result.v1",
            "tool_name": "qlip.solve",
            "execution_performed": True,
            "status": "succeeded",
            "output_summary": {"status": "OPTIMAL", "objective_value": -1.53},
            "artifact_refs": [
                {"ref_name": "solution_cif_path", "value": str(solution), "kind": "file"},
                {"ref_name": "candidate_cif_path", "value": str(solution), "kind": "file"},
            ],
            "raw_result_ref": None,
            "raw_result_summary": {"status": "OPTIMAL"},
            "error": None,
            "warnings": [],
        }

    def novelty_adapter(step, *, arguments, prior_step_results, step_dir):
        _ = step, arguments, prior_step_results, step_dir
        return {
            "schema_version": "agentic_csp.tool_execution_result.v1",
            "tool_name": "crystal.novelty_check",
            "execution_performed": True,
            "status": "succeeded",
            "output_summary": {"is_novel": True},
            "artifact_refs": [],
            "raw_result_ref": None,
            "raw_result_summary": {"is_novel": True},
            "error": None,
            "warnings": [],
        }

    return {
        "crystal.csp_pack": crystal_adapter,
        "spp.run_pipeline": spp_run_adapter,
        "spp.package_for_qlip": spp_package_adapter,
        "qlip.validate_request": validate_adapter,
        "qlip.solve": solve_adapter,
        "crystal.novelty_check": novelty_adapter,
    }


def test_demo_loop_writes_visual_report_and_execution_artifacts() -> None:
    with _local_test_dir("demo_loop") as workdir:
        settings = _fake_settings(workdir)
        result = run_demo_execution_loop(
            out_dir=workdir / "demo",
            planner_compile_run=_planner_compile_run(workdir),
            allow_real_execution=True,
            allowed_tools=[
                "crystal.csp_pack",
                "spp.run_pipeline",
                "qlip.validate_request",
                "qlip.solve",
                "crystal.novelty_check",
            ],
            adapters=get_default_tool_execution_adapters(settings),
        )

        assert result["schema_version"] == DEMO_EXECUTION_LOOP_SCHEMA_VERSION
        assert Path(result["report_markdown_path"]).exists()
        assert Path(result["workflow_evaluation_markdown_path"]).exists()
        assert Path(result["workflow_evaluation_json_path"]).exists()
        assert Path(result["execution_run_path"]).exists()
        assert Path(result["step_log_path"]).exists()
        assert result["tool_sequence"]
        assert result["executed_tool_sequence"] or result["blocked_tool_sequence"]

        markdown = Path(result["report_markdown_path"]).read_text(encoding="utf-8")
        assert "## Sequence Diagram" in markdown
        assert "## Plan Source" in markdown
        assert "## What This Demonstrates" in markdown
        assert "## LLM Plan" in markdown
        assert "## Executed Tools and Outputs" in markdown
        assert "## Final Outputs" in markdown
        assert "crystal.csp_pack" in markdown
        assert "execution_run.json" in markdown
        assert "No old hardcoded pipeline shortcut was used." in markdown
        assert "workflow_evaluation.md" in markdown
        assert Path(result["artifact_paths"]["planner_trace_md"]).exists()
        evaluation = json.loads(Path(result["artifact_paths"]["workflow_evaluation_json"]).read_text(encoding="utf-8"))
        assert evaluation["schema_version"] == "agentic_csp.workflow_evaluation.v1"
        assert evaluation["requirement_checks"]["solve_requirement"]["status"] == "pass"
        execution_run = json.loads(Path(result["execution_run_path"]).read_text(encoding="utf-8"))
        validate_step = next(
            item for item in execution_run["step_results"] if item["tool_name"] == "qlip.validate_request"
        )
        solve_step = next(item for item in execution_run["step_results"] if item["tool_name"] == "qlip.solve")
        novelty_step = next(item for item in execution_run["step_results"] if item["tool_name"] == "crystal.novelty_check")
        assert validate_step["output_summary"]["valid"] is True
        assert validate_step["output_summary"]["validated_request_written_kind"] == "normalized_request"
        assert solve_step["execution_performed"] is True
        assert solve_step["status"] == "succeeded"
        assert solve_step.get("error") is None
        solution_cif_path = next(
            item["value"] for item in solve_step["artifact_refs"] if item["ref_name"] == "solution_cif_path"
        )
        assert Path(solution_cif_path).is_absolute()
        assert Path(solution_cif_path).exists()
        assert novelty_step["execution_performed"] is True
        assert novelty_step["status"] == "succeeded"
        assert novelty_step["output_summary"]["novelty_input_cif_path"] == solution_cif_path
        report_json = json.loads(Path(result["artifact_paths"]["execution_loop_report_json"]).read_text(encoding="utf-8"))
        assert report_json["final_outputs"]["solution_cif_path"] == solution_cif_path
        assert report_json["final_outputs"]["novelty_result"]["is_novel"] is True

        bundle_result = write_demo_showcase_bundle(result, workdir / "bundle")
        manifest = json.loads(Path(bundle_result["manifest_path"]).read_text(encoding="utf-8"))
        assert (Path(bundle_result["bundle_root"]) / "report" / "workflow_evaluation.md").exists()
        assert (Path(bundle_result["bundle_root"]) / "report" / "workflow_evaluation.json").exists()
        assert manifest["workflow_evaluation_markdown_path"].endswith("report\\workflow_evaluation.md")
        assert manifest["workflow_evaluation_json_path"].endswith("report\\workflow_evaluation.json")
        readme = Path(bundle_result["readme_path"]).read_text(encoding="utf-8")
        assert "report/workflow_evaluation.md" in readme
        assert "report/execution_loop_report.md" in readme


def test_demo_loop_attempts_one_bounded_qlip_recovery_retry() -> None:
    with _local_test_dir("demo_loop_recovery_retry") as workdir:
        result = run_demo_execution_loop(
            out_dir=workdir / "demo",
            planner_compile_run=_planner_compile_run(workdir),
            allow_real_execution=True,
            allowed_tools=list(DEFAULT_DEMO_ALLOWED_TOOLS),
            adapters=_recovery_adapters(workdir, pot_root_available=True),
        )

        recovery_attempt = result["recovery_attempt"]
        assert recovery_attempt["action"] == "repackage_qlip_request"
        assert recovery_attempt["retry_validation"]["attempted"] is True
        assert recovery_attempt["retry_validation"]["valid"] is True
        assert recovery_attempt["solve"]["attempted"] is True
        assert recovery_attempt["solve"]["status"] == "succeeded"
        assert recovery_attempt["novelty"]["attempted"] is True
        assert Path(recovery_attempt["corrected_request_path"]).exists()
        assert Path(result["artifact_paths"]["recovery_step_log_jsonl"]).exists()

        markdown = Path(result["report_markdown_path"]).read_text(encoding="utf-8")
        assert "## Recovery Attempt" in markdown
        assert "retry validation valid: true" in markdown
        assert "solve attempted: true" in markdown


def test_demo_loop_partial_workflow_evaluation_reports_exact_failed_tool_and_next_action() -> None:
    with _local_test_dir("demo_loop_qlip_error_report") as workdir:
        settings = _fake_settings(workdir)
        adapters = get_default_tool_execution_adapters(settings)

        def failing_solve_adapter(step, *, arguments, prior_step_results, step_dir):
            _ = step, arguments, prior_step_results
            step_dir.mkdir(parents=True, exist_ok=True)
            raw = step_dir / "raw_tool_response.json"
            raw.write_text(json.dumps({"status": "ERROR"}, indent=2), encoding="utf-8")
            return {
                "schema_version": "agentic_csp.tool_execution_result.v1",
                "tool_name": "qlip.solve",
                "execution_performed": True,
                "status": "failed",
                "output_summary": {},
                "artifact_refs": [],
                "raw_result_ref": str(raw),
                "raw_result_summary": {"status": "ERROR"},
                "error": {"code": "non_solution_status", "message": "qlip.solve returned status=ERROR"},
                "warnings": [],
            }

        adapters["qlip.solve"] = failing_solve_adapter
        result = run_demo_execution_loop(
            out_dir=workdir / "demo",
            planner_compile_run=_planner_compile_run(workdir),
            allow_real_execution=True,
            allowed_tools=list(DEFAULT_DEMO_ALLOWED_TOOLS),
            adapters=adapters,
        )

        evaluation = json.loads(Path(result["artifact_paths"]["workflow_evaluation_json"]).read_text(encoding="utf-8"))
        markdown = Path(result["artifact_paths"]["workflow_evaluation_md"]).read_text(encoding="utf-8")

        assert evaluation["failure_assessment"]["failed_tool"] == "qlip.solve"
        assert evaluation["failure_assessment"]["classification"] == "qlip_error"
        assert "Revise the QLIP formulation" in markdown


def test_demo_loop_keeps_qlip_solve_blocked_when_recovery_has_no_real_pot_root() -> None:
    with _local_test_dir("demo_loop_recovery_blocked") as workdir:
        result = run_demo_execution_loop(
            out_dir=workdir / "demo",
            planner_compile_run=_planner_compile_run(workdir),
            allow_real_execution=True,
            allowed_tools=list(DEFAULT_DEMO_ALLOWED_TOOLS),
            adapters=_recovery_adapters(workdir, pot_root_available=False),
        )

        recovery_attempt = result["recovery_attempt"]
        assert recovery_attempt["status"] == "blocked"
        assert recovery_attempt["blocked_reason"] == "pot_root_unavailable"
        assert recovery_attempt["retry_validation"]["attempted"] is False
        assert recovery_attempt["solve"]["attempted"] is False

        execution_run = json.loads(Path(result["execution_run_path"]).read_text(encoding="utf-8"))
        assert execution_run["step_results"][3]["tool_name"] == "qlip.solve"
        assert execution_run["step_results"][3]["status"] == "blocked"


def test_showcase_plan_has_exact_five_tool_hints_and_five_executable_steps() -> None:
    run_plan = build_showcase_six_tool_run_plan()
    expected_hints = [
        "tool_hint: crystal.csp_pack",
        "tool_hint: spp.run_pipeline",
        "tool_hint: qlip.validate_request",
        "tool_hint: qlip.solve",
        "tool_hint: crystal.novelty_check",
    ]

    assert run_plan["schema_version"] == "agentic_csp.run_plan.v1"
    assert run_plan["overall_goal"] == SHOWCASE_DEFAULT_GOAL
    assert run_plan["metadata"]["plan_source"] == "deterministic_showcase"
    assert run_plan["metadata"]["live_llm_used"] is False
    assert run_plan["metadata"]["crystal_export_mode"] == "safe"
    assert run_plan["metadata"]["crystal_demo_export_enabled"] is False
    for hint in expected_hints:
        assert hint in run_plan["plan_as_text"]

    compile_result = compile_run_plan_to_tool_proposals(run_plan)
    executable_plan = build_executable_plan_from_compile_result(compile_result)
    assert [proposal["tool_name"] for proposal in compile_result["proposals"]] == [
        "crystal.csp_pack",
        "spp.run_pipeline",
        "qlip.validate_request",
        "qlip.solve",
        "crystal.novelty_check",
    ]
    assert len(executable_plan["executable_steps"]) == 5


def test_demo_loop_module_parser_and_mcp_backend_helpers() -> None:
    parser = _parser()
    args = parser.parse_args(
        [
            "--config",
            "my_live_config.yaml",
            "--goal",
            "TiO2 candidate search",
            "--out-dir",
            "test_workdir/demo_loop_showcase",
            "--material-system",
            "CoAs2",
            "--plan-source",
            "showcase",
            "--mcp-backend",
            "fake",
            "--allow-crystal-demo-export",
            "--zip",
        ]
    )

    assert args.config == "my_live_config.yaml"
    assert args.goal == "TiO2 candidate search"
    assert args.out_dir == "test_workdir/demo_loop_showcase"
    assert args.material_system == "CoAs2"
    assert args.plan_source == "showcase"
    assert args.mcp_backend == "fake"
    assert args.allow_crystal_demo_export is True
    assert args.zip is True
    assert args.run_id == "run_001"
    assert args.stage == "wide_exploration"
    assert "crystal.csp_pack" in DEFAULT_DEMO_ALLOWED_TOOLS

    with _local_test_dir("mcp_settings") as workdir:
        previous_base_url = os.environ.get("LLM_BASE_URL")
        previous_api_key = os.environ.get("LLM_API_KEY")
        previous_model = os.environ.get("LLM_MODEL")
        os.environ["LLM_BASE_URL"] = "http://127.0.0.1:11434/v1"
        os.environ["LLM_API_KEY"] = "ollama"
        os.environ["LLM_MODEL"] = "gpt-oss:20b"
        settings = build_demo_mcp_settings(workdir, "fake")
        try:
            assert settings.workspace_root == workdir
            assert "mcp_crystaldb_server.py" in str(settings.crystaldb_mcp_cmd)
            assert "mcp_spp_server.py" in str(settings.spp_mcp_cmd)
            assert "mcp_qlip_server.py" in str(settings.qlip_mcp_cmd)
            assert settings.llm_base_url == "http://127.0.0.1:11434/v1"
            assert settings.llm_api_key == "ollama"
            assert settings.llm_model == "gpt-oss:20b"
        finally:
            if previous_base_url is None:
                os.environ.pop("LLM_BASE_URL", None)
            else:
                os.environ["LLM_BASE_URL"] = previous_base_url
            if previous_api_key is None:
                os.environ.pop("LLM_API_KEY", None)
            else:
                os.environ["LLM_API_KEY"] = previous_api_key
            if previous_model is None:
                os.environ.pop("LLM_MODEL", None)
            else:
                os.environ["LLM_MODEL"] = previous_model


def test_configured_demo_mcp_settings_can_load_yaml_commands() -> None:
    with _local_test_dir("configured_mcp_settings") as workdir:
        config_path = workdir / "demo_config.yaml"
        config_path.write_text(
            "\n".join(
                [
                    "llm_base_url: http://127.0.0.1:11434/v1",
                    "llm_api_key: ollama",
                    "llm_model: gpt-oss:20b",
                    "workspace_root: .sokllm_workspace_live",
                    "crystaldb_mcp_cmd: .venv\\Scripts\\python.exe -m mcp_server.server",
                    "crystaldb_mcp_cwd: ..\\Crystal-DB",
                    "spp_mcp_cmd: C:\\Users\\brown\\Documents\\GitHub\\Skill-Loop-CSP\\.venv\\Scripts\\python.exe -m spp_maker_mcp.server",
                    "spp_mcp_cwd: ..\\SPP-Maker-QLIP",
                    "qlip_mcp_cmd: .venv\\Scripts\\python.exe -m qlip.mcp.server",
                    "qlip_mcp_cwd: ..\\qlip\\src",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        settings = build_demo_mcp_settings(workdir, "configured", config_path=config_path)

        assert settings.workspace_root == workdir
        assert settings.crystaldb_mcp_cmd == ".venv\\Scripts\\python.exe -m mcp_server.server"
        assert settings.crystaldb_mcp_cwd == "..\\Crystal-DB"
        assert settings.spp_mcp_cmd == "C:\\Users\\brown\\Documents\\GitHub\\Skill-Loop-CSP\\.venv\\Scripts\\python.exe -m spp_maker_mcp.server"
        assert settings.spp_mcp_cwd == "..\\SPP-Maker-QLIP"
        assert settings.qlip_mcp_cmd == ".venv\\Scripts\\python.exe -m qlip.mcp.server"
        assert settings.qlip_mcp_cwd == "..\\qlip\\src"


def test_configured_demo_mcp_settings_can_enable_crystal_demo_export() -> None:
    with _local_test_dir("configured_mcp_demo_export") as workdir:
        config_path = workdir / "demo_config.yaml"
        config_path.write_text(
            "\n".join(
                [
                    "crystaldb_mcp_cmd: .venv\\Scripts\\python.exe -m mcp_server.server",
                    "crystaldb_mcp_cwd: ..\\Crystal-DB",
                    "crystaldb_policy_mode: safe",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        settings = build_demo_mcp_settings(
            workdir,
            "configured",
            config_path=config_path,
            allow_crystal_demo_export=True,
        )

        assert settings.crystaldb_policy_mode == "demo"


def test_demo_loop_has_no_pipeline_or_sqlite_dependency() -> None:
    source = inspect.getsource(demo_loop_module)
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
