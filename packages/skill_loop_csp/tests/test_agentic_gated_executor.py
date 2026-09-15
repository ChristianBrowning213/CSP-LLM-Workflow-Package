from __future__ import annotations

import ast
import inspect
import json
import shutil
import sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from sok_llm_orchestrator.agentic.execution_plan_adapter import build_executable_plan_from_compile_result
from sok_llm_orchestrator.agentic.gated_executor import (
    EXECUTION_RUN_SCHEMA_VERSION,
    execute_executable_plan,
    resolve_step_placeholders,
)
from sok_llm_orchestrator.agentic.plan_compile import compile_run_plan_to_tool_proposals
import sok_llm_orchestrator.agentic.gated_executor as gated_executor_module


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


def _compile_single_crystal_plan() -> dict[str, object]:
    return compile_run_plan_to_tool_proposals(
        {
            "schema_version": "agentic_csp.run_plan.v1",
            "run_id": "run_001",
            "overall_goal": "TiO2",
            "plan_as_text": "tool_hint: crystal.csp_pack",
        }
    )


def _compile_all_six_plan() -> dict[str, object]:
    return compile_run_plan_to_tool_proposals(
        {
            "schema_version": "agentic_csp.run_plan.v1",
            "run_id": "run_001",
            "overall_goal": "TiO2",
            "plan_as_text": "\n".join(
                [
                    "tool_hint: crystal.csp_pack",
                    "tool_hint: spp.run_pipeline",
                    "tool_hint: spp.package_for_qlip",
                    "tool_hint: qlip.validate_request",
                    "tool_hint: qlip.solve",
                    "tool_hint: crystal.novelty_check",
                ]
            ),
        }
    )


def _single_step_plan(tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "agentic_csp.executable_plan.v1",
        "execution_mode": "dry_run",
        "execution_allowed": False,
        "status": "ready_for_dry_run",
        "tool_sequence": [tool_name],
        "executable_steps": [
            {
                "step_index": 0,
                "tool_name": tool_name,
                "proposal": {
                    "schema_version": "agentic_csp.tool_call_proposal.v1",
                    "tool_name": tool_name,
                    "arguments": arguments,
                },
                "arguments": arguments,
                "execution_mode": "dry_run",
                "execution_allowed": False,
                "status": "pending_dry_run",
                "audit": {"proposal_schema_version": "agentic_csp.tool_call_proposal.v1", "source": "compile_result", "placeholder_refs": []},
            }
        ],
        "blocked_reasons": [],
        "warnings": [],
    }


def test_dry_run_blocks_execution_and_writes_artifacts() -> None:
    with _local_test_dir("gated_executor_dry_run") as workdir:
        executable_plan = build_executable_plan_from_compile_result(_compile_single_crystal_plan())

        result = execute_executable_plan(
            executable_plan,
            allow_real_execution=False,
            allowed_tools=["crystal.csp_pack"],
            out_dir=workdir,
        )

        assert result["schema_version"] == EXECUTION_RUN_SCHEMA_VERSION
        assert result["status"] == "blocked"
        assert result["execution_performed"] is False
        assert result["step_results"][0]["status"] == "blocked"
        assert result["step_results"][0]["error"]["code"] == "execution_not_allowed"
        assert Path(result["artifact_paths"]["execution_run_json"]).exists()
        assert Path(result["artifact_paths"]["execution_step_log_jsonl"]).exists()


def test_allowed_tools_gating_and_unsupported_adapter_block_truthfully() -> None:
    with _local_test_dir("gated_executor_gating") as workdir:
        executable_plan = build_executable_plan_from_compile_result(_compile_single_crystal_plan())

        blocked_by_allowlist = execute_executable_plan(
            executable_plan,
            allow_real_execution=True,
            allowed_tools=["qlip.solve"],
            out_dir=workdir / "allowlist",
        )
        assert blocked_by_allowlist["step_results"][0]["error"]["code"] == "tool_not_allowed"

        blocked_by_adapter = execute_executable_plan(
            executable_plan,
            allow_real_execution=True,
            allowed_tools=["crystal.csp_pack"],
            adapters={},
            out_dir=workdir / "adapter",
        )
        assert blocked_by_adapter["step_results"][0]["error"]["code"] == "unsupported_tool_adapter"


def test_fake_adapter_success_logs_output_and_failure_stops_when_requested() -> None:
    success_plan = _single_step_plan("crystal.csp_pack", {"case_id": "run_001", "objective_family": "TiO2"})

    def success_adapter(step, *, arguments, prior_step_results, step_dir):
        _ = step
        _ = prior_step_results
        _ = step_dir
        return {
            "schema_version": "agentic_csp.tool_execution_result.v1",
            "tool_name": "crystal.csp_pack",
            "execution_performed": True,
            "status": "succeeded",
            "output_summary": {"rows": 1},
            "artifact_refs": [],
            "raw_result_ref": None,
            "raw_result_summary": {},
            "error": None,
            "warnings": [],
        }

    with _local_test_dir("gated_executor_fake_adapter") as workdir:
        success_result = execute_executable_plan(
            success_plan,
            allow_real_execution=True,
            allowed_tools=["crystal.csp_pack"],
            adapters={"crystal.csp_pack": success_adapter},
            out_dir=workdir / "success",
        )
        log_lines = (workdir / "success" / "execution_step_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert success_result["status"] == "completed"
        assert json.loads(log_lines[0])["output_summary"] == {"rows": 1}

    failure_plan = {
        **success_plan,
        "tool_sequence": ["crystal.csp_pack", "spp.run_pipeline"],
        "executable_steps": [
            success_plan["executable_steps"][0],
            {
                "step_index": 1,
                "tool_name": "spp.run_pipeline",
                "proposal": {"schema_version": "agentic_csp.tool_call_proposal.v1", "tool_name": "spp.run_pipeline", "arguments": {"case_id": "run_001", "corpus_ref": "x"}},
                "arguments": {"case_id": "run_001", "corpus_ref": "x"},
                "execution_mode": "dry_run",
                "execution_allowed": False,
                "status": "pending_dry_run",
                "audit": {"proposal_schema_version": "agentic_csp.tool_call_proposal.v1", "source": "compile_result", "placeholder_refs": []},
            },
        ],
    }

    def failure_adapter(step, *, arguments, prior_step_results, step_dir):
        _ = step
        _ = arguments
        _ = prior_step_results
        _ = step_dir
        return {
            "schema_version": "agentic_csp.tool_execution_result.v1",
            "tool_name": "crystal.csp_pack",
            "execution_performed": True,
            "status": "failed",
            "output_summary": {},
            "artifact_refs": [],
            "raw_result_ref": None,
            "raw_result_summary": {},
            "error": {"code": "adapter_failed", "message": "boom"},
            "warnings": [],
        }

        failure_result = execute_executable_plan(
            failure_plan,
            allow_real_execution=True,
            allowed_tools=["crystal.csp_pack", "spp.run_pipeline"],
            adapters={"crystal.csp_pack": failure_adapter, "spp.run_pipeline": success_adapter},
            out_dir=workdir / "failure",
            stop_on_failure=True,
        )
        assert len(failure_result["step_results"]) == 1
        assert failure_result["step_results"][0]["status"] == "failed"
        assert failure_result["stopped_reason"] == "adapter_failed"


def test_placeholder_resolution_and_unresolved_pending_ref_block_are_truthful() -> None:
    resolved = resolve_step_placeholders(
        {"case_id": "run_001", "corpus_ref": "pending_corpus_ref"},
        [
            {
                "artifact_refs": [
                    {"ref_name": "corpus_ref", "value": "C:\\tmp\\cifs", "kind": "directory"},
                ]
            }
        ],
    )
    assert resolved["corpus_ref"] == "C:\\tmp\\cifs"

    unresolved_plan = _single_step_plan(
        "spp.run_pipeline",
        {"case_id": "run_001", "corpus_ref": "pending_corpus_ref"},
    )
    with _local_test_dir("gated_executor_unresolved_ref") as workdir:
        result = execute_executable_plan(
            unresolved_plan,
            allow_real_execution=True,
            allowed_tools=["spp.run_pipeline"],
            adapters={"spp.run_pipeline": lambda **_: {}},
            out_dir=workdir / "unresolved",
        )
        assert result["status"] == "blocked"
        assert result["step_results"][0]["error"]["code"] == "unresolved_placeholder_ref"


def test_unresolved_corpus_ref_reports_crystal_export_block_reason() -> None:
    executable_plan = {
        "schema_version": "agentic_csp.executable_plan.v1",
        "execution_mode": "real",
        "execution_allowed": True,
        "status": "ready_for_real_execution",
        "tool_sequence": ["crystal.csp_pack", "spp.run_pipeline"],
        "executable_steps": [
            {
                "step_index": 0,
                "tool_name": "crystal.csp_pack",
                "proposal": {"schema_version": "agentic_csp.tool_call_proposal.v1", "tool_name": "crystal.csp_pack", "arguments": {"case_id": "run_001"}},
                "arguments": {"case_id": "run_001"},
                "execution_mode": "real",
                "execution_allowed": True,
                "status": "pending_real_execution",
                "audit": {"proposal_schema_version": "agentic_csp.tool_call_proposal.v1", "source": "compile_result", "placeholder_refs": []},
            },
            {
                "step_index": 1,
                "tool_name": "spp.run_pipeline",
                "proposal": {
                    "schema_version": "agentic_csp.tool_call_proposal.v1",
                    "tool_name": "spp.run_pipeline",
                    "arguments": {"case_id": "run_001", "corpus_ref": "pending_corpus_ref"},
                },
                "arguments": {"case_id": "run_001", "corpus_ref": "pending_corpus_ref"},
                "execution_mode": "real",
                "execution_allowed": True,
                "status": "pending_real_execution",
                "audit": {"proposal_schema_version": "agentic_csp.tool_call_proposal.v1", "source": "compile_result", "placeholder_refs": ["corpus_ref"]},
            },
        ],
        "blocked_reasons": [],
        "warnings": [],
    }

    def crystal_blocked_export_adapter(step, *, arguments, prior_step_results, step_dir):
        _ = step, arguments, prior_step_results, step_dir
        return {
            "schema_version": "agentic_csp.tool_execution_result.v1",
            "tool_name": "crystal.csp_pack",
            "execution_performed": True,
            "status": "succeeded",
            "output_summary": {
                "neighbor_count": 10,
                "exported_cif_count": 0,
                "export_block_reasons": ["policy_blocked: allow_export=0 and demo_export=false"],
            },
            "artifact_refs": [],
            "raw_result_ref": None,
            "raw_result_summary": {},
            "error": None,
            "warnings": [],
        }

    with _local_test_dir("gated_executor_corpus_export_blocked") as workdir:
        result = execute_executable_plan(
            executable_plan,
            allow_real_execution=True,
            allowed_tools=["crystal.csp_pack", "spp.run_pipeline"],
            adapters={"crystal.csp_pack": crystal_blocked_export_adapter, "spp.run_pipeline": lambda **_: {}},
            out_dir=workdir,
        )

        assert result["status"] == "partial"
        assert result["step_results"][1]["status"] == "blocked"
        assert result["step_results"][1]["error"]["code"] == "corpus_export_blocked"
        assert "policy_blocked: allow_export=0 and demo_export=false" in result["step_results"][1]["error"]["message"]


def test_invalid_qlip_validation_blocks_qlip_solve_truthfully() -> None:
    executable_plan = {
        "schema_version": "agentic_csp.executable_plan.v1",
        "execution_mode": "real",
        "execution_allowed": True,
        "status": "ready_for_real_execution",
        "tool_sequence": ["qlip.validate_request", "qlip.solve"],
        "executable_steps": [
            {
                "step_index": 0,
                "tool_name": "qlip.validate_request",
                "proposal": {
                    "schema_version": "agentic_csp.tool_call_proposal.v1",
                    "tool_name": "qlip.validate_request",
                    "arguments": {"case_id": "run_001", "request_ref": "C:\\tmp\\request.json"},
                },
                "arguments": {"case_id": "run_001", "request_ref": "C:\\tmp\\request.json"},
                "execution_mode": "real",
                "execution_allowed": True,
                "status": "pending_real_execution",
                "audit": {"proposal_schema_version": "agentic_csp.tool_call_proposal.v1", "source": "compile_result", "placeholder_refs": []},
            },
            {
                "step_index": 1,
                "tool_name": "qlip.solve",
                "proposal": {
                    "schema_version": "agentic_csp.tool_call_proposal.v1",
                    "tool_name": "qlip.solve",
                    "arguments": {"case_id": "run_001", "validated_request_ref": "C:\\tmp\\validated_request.json"},
                },
                "arguments": {"case_id": "run_001", "validated_request_ref": "C:\\tmp\\validated_request.json"},
                "execution_mode": "real",
                "execution_allowed": True,
                "status": "pending_real_execution",
                "audit": {"proposal_schema_version": "agentic_csp.tool_call_proposal.v1", "source": "compile_result", "placeholder_refs": []},
            },
        ],
        "blocked_reasons": [],
        "warnings": [],
    }

    def invalid_validate_adapter(step, *, arguments, prior_step_results, step_dir):
        _ = step, arguments, prior_step_results, step_dir
        return {
            "schema_version": "agentic_csp.tool_execution_result.v1",
            "tool_name": "qlip.validate_request",
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
            "artifact_refs": [{"ref_name": "validated_request_ref", "value": "C:\\tmp\\validated_request.json", "kind": "file"}],
            "raw_result_ref": None,
            "raw_result_summary": {"valid": False},
            "error": None,
            "warnings": [],
        }

    with _local_test_dir("gated_executor_invalid_qlip_validation") as workdir:
        result = execute_executable_plan(
            executable_plan,
            allow_real_execution=True,
            allowed_tools=["qlip.validate_request", "qlip.solve"],
            adapters={"qlip.validate_request": invalid_validate_adapter, "qlip.solve": lambda **_: {}},
            out_dir=workdir,
        )

        assert result["status"] == "partial"
        assert result["step_results"][1]["execution_performed"] is False
        assert result["step_results"][1]["status"] == "blocked"
        assert result["step_results"][1]["error"]["code"] == "qlip_request_invalid"
        assert "pot_root_missing" in result["step_results"][1]["error"]["message"]


def test_valid_qlip_validation_allows_qlip_solve() -> None:
    executable_plan = {
        "schema_version": "agentic_csp.executable_plan.v1",
        "execution_mode": "real",
        "execution_allowed": True,
        "status": "ready_for_real_execution",
        "tool_sequence": ["qlip.validate_request", "qlip.solve"],
        "executable_steps": [
            {
                "step_index": 0,
                "tool_name": "qlip.validate_request",
                "proposal": {
                    "schema_version": "agentic_csp.tool_call_proposal.v1",
                    "tool_name": "qlip.validate_request",
                    "arguments": {"case_id": "run_001", "request_ref": "C:\\tmp\\request.json"},
                },
                "arguments": {"case_id": "run_001", "request_ref": "C:\\tmp\\request.json"},
                "execution_mode": "real",
                "execution_allowed": True,
                "status": "pending_real_execution",
                "audit": {"proposal_schema_version": "agentic_csp.tool_call_proposal.v1", "source": "compile_result", "placeholder_refs": []},
            },
            {
                "step_index": 1,
                "tool_name": "qlip.solve",
                "proposal": {
                    "schema_version": "agentic_csp.tool_call_proposal.v1",
                    "tool_name": "qlip.solve",
                    "arguments": {"case_id": "run_001", "validated_request_ref": "C:\\tmp\\validated_request.json"},
                },
                "arguments": {"case_id": "run_001", "validated_request_ref": "C:\\tmp\\validated_request.json"},
                "execution_mode": "real",
                "execution_allowed": True,
                "status": "pending_real_execution",
                "audit": {"proposal_schema_version": "agentic_csp.tool_call_proposal.v1", "source": "compile_result", "placeholder_refs": []},
            },
        ],
        "blocked_reasons": [],
        "warnings": [],
    }

    def valid_validate_adapter(step, *, arguments, prior_step_results, step_dir):
        _ = step, arguments, prior_step_results, step_dir
        return {
            "schema_version": "agentic_csp.tool_execution_result.v1",
            "tool_name": "qlip.validate_request",
            "execution_performed": True,
            "status": "succeeded",
            "output_summary": {"valid": True, "validation_errors": []},
            "artifact_refs": [{"ref_name": "validated_request_ref", "value": "C:\\tmp\\validated_request.json", "kind": "file"}],
            "raw_result_ref": None,
            "raw_result_summary": {"valid": True},
            "error": None,
            "warnings": [],
        }

    def solve_adapter(step, *, arguments, prior_step_results, step_dir):
        _ = step, arguments, prior_step_results, step_dir
        return {
            "schema_version": "agentic_csp.tool_execution_result.v1",
            "tool_name": "qlip.solve",
            "execution_performed": True,
            "status": "succeeded",
            "output_summary": {"status": "OPTIMAL"},
            "artifact_refs": [],
            "raw_result_ref": None,
            "raw_result_summary": {"status": "OPTIMAL"},
            "error": None,
            "warnings": [],
        }

    with _local_test_dir("gated_executor_valid_qlip_validation") as workdir:
        result = execute_executable_plan(
            executable_plan,
            allow_real_execution=True,
            allowed_tools=["qlip.validate_request", "qlip.solve"],
            adapters={"qlip.validate_request": valid_validate_adapter, "qlip.solve": solve_adapter},
            out_dir=workdir,
        )

        assert result["status"] == "completed"
        assert result["step_results"][1]["execution_performed"] is True
        assert result["step_results"][1]["status"] == "succeeded"


def test_gated_executor_is_deterministic_json_serializable_and_does_not_mutate_input() -> None:
    with _local_test_dir("gated_executor_deterministic") as workdir:
        executable_plan = build_executable_plan_from_compile_result(_compile_all_six_plan())
        before = deepcopy(executable_plan)

        result = execute_executable_plan(
            executable_plan,
            allow_real_execution=False,
            allowed_tools=["crystal.csp_pack"],
            out_dir=workdir,
        )

        assert json.loads(json.dumps(result))["schema_version"] == EXECUTION_RUN_SCHEMA_VERSION
        assert executable_plan == before


def test_gated_executor_has_no_pipeline_or_sqlite_dependency() -> None:
    source = inspect.getsource(gated_executor_module)
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


def test_gated_executor_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    _ = execute_executable_plan(
        build_executable_plan_from_compile_result(_compile_single_crystal_plan()),
        allow_real_execution=False,
        allowed_tools=["crystal.csp_pack"],
        out_dir=Path.cwd() / "test_workdir" / "agentic_gated_executor_no_pipeline",
    )
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
