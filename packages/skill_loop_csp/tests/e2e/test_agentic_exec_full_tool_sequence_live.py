from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from sok_llm_orchestrator.agentic.execution_plan_adapter import build_executable_plan_from_compile_result
from sok_llm_orchestrator.agentic.gated_executor import execute_executable_plan
from sok_llm_orchestrator.agentic.plan_compile import compile_run_plan_to_tool_proposals
from sok_llm_orchestrator.agentic.tool_execution_adapters import get_default_tool_execution_adapters
from sok_llm_orchestrator.config import Settings


pytestmark = pytest.mark.live_e2e


def _require_live_e2e() -> None:
    if os.environ.get("RUN_LIVE_E2E_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_E2E_TESTS=1 to run live execution tests.")


def _fake_live_settings(workdir: Path) -> Settings:
    root = Path(__file__).resolve().parents[2]
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


def test_live_exec_full_tool_sequence_from_parsed_plan_captures_real_outputs() -> None:
    _require_live_e2e()
    root = Path.cwd() / "test_workdir" / "agentic_exec_full_tool_sequence_live"
    root.mkdir(parents=True, exist_ok=True)
    case_dir = root / "case_exec_full_tool_sequence"
    case_dir.mkdir(parents=True, exist_ok=True)

    compile_result = compile_run_plan_to_tool_proposals(
        {
            "schema_version": "agentic_csp.run_plan.v1",
            "run_id": "run_001",
            "overall_goal": "TiO2",
            "run_goal": "execute the parsed six-tool CSP workflow through the real MCP adapter boundary",
            "stage": "wide_exploration",
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
    executable_plan = build_executable_plan_from_compile_result(compile_result)
    settings = _fake_live_settings(case_dir)
    adapters = get_default_tool_execution_adapters(settings)

    result = execute_executable_plan(
        executable_plan,
        allow_real_execution=True,
        allowed_tools=[
            "crystal.csp_pack",
            "crystal.novelty_check",
            "spp.run_pipeline",
            "spp.package_for_qlip",
            "qlip.validate_request",
            "qlip.solve",
        ],
        adapters=adapters,
        out_dir=case_dir / "execution",
    )

    print(f"AGENTIC_EXECUTION_RUN_JSON={result['artifact_paths']['execution_run_json']}")
    print(f"AGENTIC_EXECUTION_STEP_LOG_JSONL={result['artifact_paths']['execution_step_log_jsonl']}")
    print(f"AGENTIC_EXECUTED_TOOL_SEQUENCE={json.dumps(result['executed_tool_sequence'])}")

    assert result["schema_version"] == "agentic_csp.execution_run.v1"
    assert Path(result["artifact_paths"]["execution_run_json"]).exists()
    assert Path(result["artifact_paths"]["execution_step_log_jsonl"]).exists()
    assert result["status"] in {"completed", "partial", "blocked", "failed"}
    assert result["executed_tool_sequence"]
    assert all(
        step["execution_performed"] is True
        for step in result["step_results"]
        if step["status"] == "succeeded"
    )
    assert all(
        step["status"] != "succeeded" or step["artifact_refs"] is not None
        for step in result["step_results"]
    )
    assert all(
        step["status"] != "blocked" or step["error"]
        for step in result["step_results"]
    )
    assert result["stopped_reason"] is None or isinstance(result["stopped_reason"], str)
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
