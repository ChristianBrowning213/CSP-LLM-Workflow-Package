from __future__ import annotations

import json
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from sok_llm_orchestrator.agentic.gated_executor import execute_executable_plan
from sok_llm_orchestrator.agentic.tool_execution_adapters import get_default_tool_execution_adapters
from sok_llm_orchestrator.config import Settings


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


def _five_step_plan() -> dict[str, object]:
    steps = [
        ("crystal.csp_pack", {"case_id": "run_001", "objective_family": "CoAs2"}),
        ("spp.run_pipeline", {"case_id": "run_001", "corpus_ref": "pending_corpus_ref"}),
        ("qlip.validate_request", {"case_id": "run_001", "request_ref": "pending_request_ref"}),
        ("qlip.solve", {"case_id": "run_001", "validated_request_ref": "pending_validated_request_ref"}),
        ("crystal.novelty_check", {"case_id": "run_001"}),
    ]
    return {
        "schema_version": "agentic_csp.executable_plan.v1",
        "execution_mode": "real",
        "execution_allowed": True,
        "status": "ready_for_real_execution",
        "tool_sequence": [name for name, _ in steps],
        "executable_steps": [
            {
                "step_index": index,
                "tool_name": name,
                "proposal": {
                    "schema_version": "agentic_csp.tool_call_proposal.v1",
                    "tool_name": name,
                    "arguments": arguments,
                },
                "arguments": arguments,
                "execution_mode": "real",
                "execution_allowed": True,
                "status": "pending_real_execution",
                "audit": {"proposal_schema_version": "agentic_csp.tool_call_proposal.v1", "source": "test", "placeholder_refs": []},
            }
            for index, (name, arguments) in enumerate(steps)
        ],
        "blocked_reasons": [],
        "warnings": [],
    }


def test_agentic_route_consumes_unified_spp_run_pipeline_output() -> None:
    with _local_test_dir("unified_spp_route") as workdir:
        result = execute_executable_plan(
            _five_step_plan(),
            allow_real_execution=True,
            allowed_tools=[
                "crystal.csp_pack",
                "spp.run_pipeline",
                "qlip.validate_request",
                "qlip.solve",
                "crystal.novelty_check",
            ],
            adapters=get_default_tool_execution_adapters(_fake_settings(workdir)),
            out_dir=workdir,
            stop_on_failure=True,
        )

        assert "spp.package_for_qlip" not in result["executed_tool_sequence"]
        spp_result = result["step_results"][1]
        assert spp_result["tool_name"] == "spp.run_pipeline"
        assert spp_result["output_summary"]["qlip_package_status"] == "ready"
        assert spp_result["output_summary"]["qlip_solve_compatible"] is True
        assert spp_result["output_summary"]["qlip_package_missing"] == []
        assert spp_result["output_summary"]["pot_root"]
        assert any(item["ref_name"] == "pot_root" for item in spp_result["artifact_refs"])
        assert any(item["ref_name"] == "spp_pot_root" for item in spp_result["artifact_refs"])
        request_ref = next(item["value"] for item in spp_result["artifact_refs"] if item["ref_name"] == "request_ref")
        request = json.loads(Path(request_ref).read_text(encoding="utf-8"))
        assert request["context"]["pot_root"] == spp_result["output_summary"]["pot_root"]
        assert request["guidance"][0]["params"] == {}
        assert "spp_package_path" not in request["guidance"][0]["params"]
        assert result["step_results"][2]["tool_name"] == "qlip.validate_request"


def test_failed_unified_packaging_surfaces_errors_and_does_not_emit_request() -> None:
    def failed_spp_adapter(step, *, arguments, prior_step_results, step_dir):
        _ = step, arguments, prior_step_results, step_dir
        return {
            "schema_version": "agentic_csp.tool_execution_result.v1",
            "tool_name": "spp.run_pipeline",
            "execution_performed": True,
            "status": "succeeded",
            "output_summary": {
                "run_root": "C:\\demo\\spp_run",
                "qlip_package_status": "failed",
                "qlip_solve_compatible": False,
                "qlip_package_errors": [{"code": "qlip_packaging_failed", "message": "boom"}],
            },
            "artifact_refs": [{"ref_name": "spp_package_ref", "value": "C:\\demo\\spp_run", "kind": "directory"}],
            "raw_result_ref": None,
            "raw_result_summary": {},
            "error": None,
            "warnings": ["{\"code\":\"qlip_packaging_failed\",\"message\":\"boom\"}"],
        }

    plan = {
        "schema_version": "agentic_csp.executable_plan.v1",
        "execution_mode": "real",
        "execution_allowed": True,
        "status": "ready_for_real_execution",
        "tool_sequence": ["spp.run_pipeline", "qlip.validate_request"],
        "executable_steps": [
            {
                "step_index": 0,
                "tool_name": "spp.run_pipeline",
                "proposal": {"schema_version": "agentic_csp.tool_call_proposal.v1", "tool_name": "spp.run_pipeline", "arguments": {"corpus_ref": "C:\\demo\\cifs"}},
                "arguments": {"corpus_ref": "C:\\demo\\cifs"},
                "execution_mode": "real",
                "execution_allowed": True,
                "status": "pending_real_execution",
                "audit": {},
            },
            {
                "step_index": 1,
                "tool_name": "qlip.validate_request",
                "proposal": {"schema_version": "agentic_csp.tool_call_proposal.v1", "tool_name": "qlip.validate_request", "arguments": {"request_ref": "pending_request_ref"}},
                "arguments": {"request_ref": "pending_request_ref"},
                "execution_mode": "real",
                "execution_allowed": True,
                "status": "pending_real_execution",
                "audit": {},
            },
        ],
        "blocked_reasons": [],
        "warnings": [],
    }

    with _local_test_dir("unified_spp_failed") as workdir:
        result = execute_executable_plan(
            plan,
            allow_real_execution=True,
            allowed_tools=["spp.run_pipeline", "qlip.validate_request"],
            adapters={"spp.run_pipeline": failed_spp_adapter},
            out_dir=workdir,
        )

        assert result["status"] == "partial"
        assert result["step_results"][0]["output_summary"]["qlip_package_errors"][0]["message"] == "boom"
        assert result["step_results"][1]["status"] == "blocked"
        error = result["step_results"][1]["error"]
        assert error["code"] == "spp_request_ref_unavailable"
        assert "SPP did not emit a solve-compatible QLIP request_ref" in error["message"]
        assert "qlip_package_status=failed" in error["message"]
        assert "qlip_solve_compatible=false" in error["message"]


def test_pair_coverage_partial_output_blocks_validate_with_clear_pairs() -> None:
    def partial_spp_adapter(step, *, arguments, prior_step_results, step_dir):
        _ = step, arguments, prior_step_results, step_dir
        return {
            "schema_version": "agentic_csp.tool_execution_result.v1",
            "tool_name": "spp.run_pipeline",
            "execution_performed": True,
            "status": "succeeded",
            "output_summary": {
                "run_root": "C:\\demo\\spp_run",
                "qlip_package_status": "partial",
                "qlip_solve_compatible": False,
                "qlip_package_missing": ["pot_pair_coverage"],
                "qlip_package_required_pairs": ["As-As", "As-Co", "Co-Co"],
                "qlip_package_missing_pairs": ["As-Co"],
                "qlip_package_errors": [{"code": "pot_pair_coverage_missing", "message": "missing As-Co"}],
            },
            "artifact_refs": [{"ref_name": "spp_package_ref", "value": "C:\\demo\\spp_run", "kind": "directory"}],
            "raw_result_ref": None,
            "raw_result_summary": {},
            "error": None,
            "warnings": ["{\"code\":\"pot_pair_coverage_missing\",\"message\":\"missing As-Co\"}"],
        }

    plan = {
        "schema_version": "agentic_csp.executable_plan.v1",
        "execution_mode": "real",
        "execution_allowed": True,
        "status": "ready_for_real_execution",
        "tool_sequence": ["spp.run_pipeline", "qlip.validate_request"],
        "executable_steps": [
            {
                "step_index": 0,
                "tool_name": "spp.run_pipeline",
                "proposal": {"schema_version": "agentic_csp.tool_call_proposal.v1", "tool_name": "spp.run_pipeline", "arguments": {"corpus_ref": "C:\\demo\\cifs"}},
                "arguments": {"corpus_ref": "C:\\demo\\cifs"},
                "execution_mode": "real",
                "execution_allowed": True,
                "status": "pending_real_execution",
                "audit": {},
            },
            {
                "step_index": 1,
                "tool_name": "qlip.validate_request",
                "proposal": {"schema_version": "agentic_csp.tool_call_proposal.v1", "tool_name": "qlip.validate_request", "arguments": {"request_ref": "pending_request_ref"}},
                "arguments": {"request_ref": "pending_request_ref"},
                "execution_mode": "real",
                "execution_allowed": True,
                "status": "pending_real_execution",
                "audit": {},
            },
        ],
        "blocked_reasons": [],
        "warnings": [],
    }

    with _local_test_dir("unified_spp_pair_coverage") as workdir:
        result = execute_executable_plan(
            plan,
            allow_real_execution=True,
            allowed_tools=["spp.run_pipeline", "qlip.validate_request"],
            adapters={"spp.run_pipeline": partial_spp_adapter},
            out_dir=workdir,
        )

        spp_summary = result["step_results"][0]["output_summary"]
        assert spp_summary["qlip_package_missing"] == ["pot_pair_coverage"]
        assert spp_summary["qlip_package_missing_pairs"] == ["As-Co"]
        assert result["step_results"][1]["status"] == "blocked"
        error = result["step_results"][1]["error"]
        assert error["code"] == "spp_request_ref_unavailable"
        assert "SPP did not emit a solve-compatible QLIP request_ref" in error["message"]
        assert "qlip_package_status=partial" in error["message"]
        assert "qlip_solve_compatible=false" in error["message"]
        assert "As-Co" in error["message"]
