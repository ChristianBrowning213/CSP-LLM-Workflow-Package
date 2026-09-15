from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from sok_llm_orchestrator.agentic.execution_plan_adapter import (
    build_executable_plan_from_compile_result,
    build_executable_plan_report,
)
from sok_llm_orchestrator.agentic.plan_compile import build_tool_parse_report
from sok_llm_orchestrator.agentic.planner_runtime import run_live_planner_and_compile
from sok_llm_orchestrator.agentic.llm_runtime import AgentLLMRuntime
from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.llm.client import LLMClient


pytestmark = pytest.mark.live_llm


def _require_live_settings() -> Settings:
    if os.environ.get("RUN_LIVE_LLM_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_LLM_TESTS=1 to run live LLM tests.")
    settings = Settings.from_sources(None)
    if settings.llm_api_key is None or settings.llm_model is None:
        pytest.skip("Live LLM settings are not configured.")
    return settings


def _find_unexpected_execution_artifacts(root: Path) -> list[str]:
    unexpected: list[str] = []
    for path in root.rglob("*"):
        name = path.name.lower()
        if path.is_file() and name.startswith("mcp") and name.endswith(".jsonl"):
            unexpected.append(str(path))
        if path.is_dir() and "tool_execution" in name:
            unexpected.append(str(path))
    return sorted(unexpected)


def test_live_planner_tool_parse_reports_valid_subset_without_execution() -> None:
    settings = _require_live_settings()
    client = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "",
        model=settings.llm_model or "",
        timeout_s=settings.llm_timeout_s,
        max_retries=1,
    )
    runtime = AgentLLMRuntime(client=client, max_attempts=2)

    root = Path.cwd() / "test_workdir" / "agentic_live_tool_parse"
    root.mkdir(parents=True, exist_ok=True)
    case_dir = root / f"case_{uuid4().hex}"
    case_dir.mkdir()

    result = run_live_planner_and_compile(
        runtime,
        {
            "run_id": "run_001",
            "overall_goal": "TiO2",
            "run_goal": (
                "propose a future csp workflow sequence from retrieval through novelty review "
                "with at least crystal.csp_pack and one later qlip or spp step"
            ),
            "stage": "wide_exploration",
        },
        out_dir=case_dir,
        archive_trace=True,
        require_proposals=True,
    )
    compile_result = result["compile_result"]
    parse_report = build_tool_parse_report(compile_result, route_mode="live_ab_parse")
    executable_plan = build_executable_plan_from_compile_result(compile_result)
    executable_plan_report = build_executable_plan_report(executable_plan)
    trace_json_path = Path(result["trace_write"]["trace_json_path"])

    print(f"AGENTIC_TOOL_PARSE_REPORT={json.dumps(parse_report, sort_keys=True)}")
    print(f"AGENTIC_EXECUTABLE_PLAN_REPORT={json.dumps(executable_plan_report, sort_keys=True)}")
    print(f"AGENTIC_TRACE_JSON={trace_json_path}")

    assert result["schema_version"] == "agentic_csp.planner_compile_run.v1"
    assert parse_report["schema_version"] == "agentic_csp.tool_parse_report.v1"
    assert executable_plan["schema_version"] == "agentic_csp.executable_plan.v1"
    assert executable_plan["execution_mode"] == "dry_run"
    assert executable_plan["execution_allowed"] is False
    assert parse_report["proposal_count"] == result["proposal_count"]
    assert parse_report["valid_count"] == result["valid_proposal_count"]
    assert parse_report["invalid_count"] == result["invalid_proposal_count"]
    assert result["valid_proposal_count"] >= 1
    assert result["invalid_proposal_count"] == 0
    assert executable_plan["status"] == "ready_for_dry_run"
    assert len(executable_plan["executable_steps"]) == result["valid_proposal_count"]
    assert all(step["execution_allowed"] is False for step in executable_plan["executable_steps"])
    assert "crystal.csp_pack" in parse_report["tool_sequence"]
    emitted_tools = {item["tool_name"] for item in compile_result["proposals"]}
    known_tools = {
        "crystal.csp_pack",
        "crystal.novelty_check",
        "spp.run_pipeline",
        "spp.package_for_qlip",
        "qlip.validate_request",
        "qlip.solve",
    }
    assert emitted_tools <= known_tools
    assert all(
        item["valid"] is True
        for item in compile_result["validation_results"]
        if item["tool_name"] in emitted_tools
    )
    assert trace_json_path.exists()
    assert _find_unexpected_execution_artifacts(case_dir) == []
