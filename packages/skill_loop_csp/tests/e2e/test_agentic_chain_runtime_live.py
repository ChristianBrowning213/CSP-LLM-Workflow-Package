from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from sok_llm_orchestrator.agentic.chain_fixtures import (
    load_chain_fixture,
    replay_c_layer_from_fixture,
    write_chain_fixture,
)
from sok_llm_orchestrator.agentic.chain_runtime import run_live_proposal_review_chain
from sok_llm_orchestrator.agentic.llm_runtime import AgentLLMRuntime
from sok_llm_orchestrator.agentic.schemas import (
    ORCHESTRATOR_DECISION_SCHEMA_VERSION,
    RUN_EVALUATION_SCHEMA_VERSION,
    RUN_MANAGER_LOG_SCHEMA_VERSION,
    RUN_PLAN_SCHEMA_VERSION,
)
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


def test_live_proposal_review_chain_writes_bundle_and_traces() -> None:
    settings = _require_live_settings()
    client = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "",
        model=settings.llm_model or "",
        timeout_s=settings.llm_timeout_s,
        max_retries=1,
    )
    runtime = AgentLLMRuntime(client=client, max_attempts=2)

    root = Path.cwd() / "test_workdir" / "agentic_live_chain_runtime"
    root.mkdir(parents=True, exist_ok=True)
    case_dir = root / f"case_{uuid4().hex}"
    case_dir.mkdir()

    result = run_live_proposal_review_chain(
        runtime,
        {
            "run_id": "run_001",
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
        },
        case_dir,
        archive_traces=True,
        require_proposals=True,
        collect_stage_timings=True,
    )
    fixture_dir = case_dir / "fixture"
    fixture_write = write_chain_fixture(result, fixture_dir)
    loaded_fixture = load_chain_fixture(fixture_write["fixture_json_path"])
    replay = replay_c_layer_from_fixture(
        loaded_fixture,
        write_manager_artifacts_dir=case_dir / "replay" / "artifacts",
    )

    chain_json_path = case_dir / "agentic_proposal_review_chain.json"
    chain_markdown_path = case_dir / "agentic_proposal_review_chain_summary.md"
    fixture_json_path = Path(fixture_write["fixture_json_path"])
    manager_notes_path = Path(replay["manager_replay_artifacts"]["manager_notes_path"])
    tool_call_log_path = Path(replay["manager_replay_artifacts"]["tool_call_log_path"])
    tool_call_log_rows = [
        json.loads(line)
        for line in tool_call_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    print(f"AGENTIC_CHAIN_JSON={chain_json_path}")
    print(f"AGENTIC_CHAIN_FIXTURE_JSON={fixture_json_path}")
    print(f"AGENTIC_CHAIN_MD={chain_markdown_path}")
    print(f"AGENTIC_MANAGER_NOTES_JSON={manager_notes_path}")
    print(f"AGENTIC_TOOL_CALL_LOG_JSONL={tool_call_log_path}")
    print(f"AGENTIC_STAGE_TIMINGS={json.dumps(result['stage_timings'], sort_keys=True)}")
    print(
        "AGENTIC_C_REPLAY_STATUS="
        + json.dumps(
            {
                "execution_intent_status": replay["execution_intent"]["status"],
                "execution_handoff_status": replay["execution_handoff"]["status"],
                "executor_preflight_status": replay["executor_preflight"]["status"],
                "noop_execution_report_status": replay["noop_execution_report"]["status"],
            },
            sort_keys=True,
        )
    )
    print(
        "AGENTIC_C_REPLAY_REPORT="
        + json.dumps(replay["c_layer_replay_report"], sort_keys=True)
    )
    for agent_name in ("planner", "run_manager", "evaluator", "orchestrator"):
        agent_paths = result["trace_paths"][agent_name]
        print(f"AGENTIC_TRACE_JSON={agent_paths['json']}")
        print(f"AGENTIC_TRACE_MD={agent_paths['markdown']}")

    assert result["schema_version"] == "agentic_csp.proposal_review_chain.v1"
    assert result["route_mode"] == "full_live_agent_chain"
    assert result["planner_result"]["run_plan"]["schema_version"] == RUN_PLAN_SCHEMA_VERSION
    assert result["run_manager_log"]["schema_version"] == RUN_MANAGER_LOG_SCHEMA_VERSION
    assert result["run_evaluation"]["schema_version"] == RUN_EVALUATION_SCHEMA_VERSION
    assert (
        result["orchestrator_decision"]["schema_version"]
        == ORCHESTRATOR_DECISION_SCHEMA_VERSION
    )
    assert result["execution_intent"]["schema_version"] == "agentic_csp.execution_intent.v1"
    assert result["execution_intent"]["status"] == "ready_for_execution"
    assert result["execution_intent"]["execution_allowed"] is True
    assert result["execution_handoff"]["schema_version"] == "agentic_csp.execution_handoff.v1"
    assert result["execution_handoff"]["status"] == "ready"
    assert result["execution_handoff"]["execution_allowed"] is True
    assert result["executor_preflight"]["schema_version"] == "agentic_csp.executor_preflight.v1"
    assert result["executor_preflight"]["status"] == "blocked"
    assert result["executor_preflight"]["dry_run_only"] is True
    assert result["executor_preflight"]["execution_allowed"] is False
    assert (
        "operator_allows_execution" in result["executor_preflight"]["missing_requirements"]
        or "workspace_writeable" in result["executor_preflight"]["missing_requirements"]
    )
    assert result["noop_execution_report"]["schema_version"] == "agentic_csp.noop_execution_report.v1"
    assert result["noop_execution_report"]["status"] == "blocked"
    assert result["noop_execution_report"]["execution_performed"] is False
    assert result["noop_execution_report"]["dry_run_only"] is True
    assert result["noop_execution_report"]["would_call_tools"] == []
    for key in (
        "planner_compile",
        "run_manager",
        "evaluator",
        "orchestrator",
        "execution_intent",
        "execution_handoff",
        "executor_preflight",
        "noop_execution_report",
        "archive_write_total",
        "bundle_write",
        "total",
    ):
        assert key in result["stage_timings"]
        assert isinstance(result["stage_timings"][key], (int, float))
    assert result["planner_result"]["proposal_count"] >= 1
    assert result["planner_result"]["valid_proposal_count"] >= 1
    compile_result = result["planner_result"]["compile_result"]
    assert compile_result["proposals"][0]["tool_name"] == "crystal.csp_pack"
    assert compile_result["validation_results"][0]["valid"] is True
    assert result["execution_intent"]["selected_proposals"][0]["tool_name"] == "crystal.csp_pack"
    assert result["execution_handoff"]["selected_tool_sequence"] == ["crystal.csp_pack"]
    assert result["execution_handoff"]["selected_proposals"][0]["tool_name"] == "crystal.csp_pack"
    assert result["execution_handoff"]["preflight_requirements"]
    assert replay["schema_version"] == "agentic_csp.c_layer_replay.v1"
    assert replay["route_mode"] == "fixture_replay_c_layer"
    assert replay["execution_intent"]["status"] == result["execution_intent"]["status"]
    assert replay["execution_handoff"]["status"] == result["execution_handoff"]["status"]
    assert replay["executor_preflight"]["status"] == result["executor_preflight"]["status"]
    assert replay["step_execution_plan"]["schema_version"] == "agentic_csp.step_execution_plan.v1"
    assert replay["step_execution_plan"]["status"] == "ready"
    assert replay["step_execution_plan"]["steps"][0]["tool_name"] == "crystal.csp_pack"
    assert replay["noop_step_execution"]["schema_version"] == "agentic_csp.noop_step_execution.v1"
    assert replay["noop_step_execution"]["execution_performed"] is False
    assert replay["noop_step_execution"]["status"] == "completed"
    assert replay["noop_step_execution"]["step_results"][0]["tool_name"] == "crystal.csp_pack"
    assert replay["noop_step_execution"]["step_results"][0]["status"] == "would_execute"
    assert replay["result_inspection"]["schema_version"] == "agentic_csp.result_inspection.v1"
    assert replay["result_inspection"]["status"] == "clear"
    assert replay["result_inspection"]["inspected_steps"][0]["tool_name"] == "crystal.csp_pack"
    assert replay["result_inspection"]["inspected_steps"][0]["inspection_status"] == "clear"
    assert replay["result_inspection"]["inspected_steps"][0]["recommended_action"] == "continue"
    assert replay["failure_handling"]["schema_version"] == "agentic_csp.failure_handling.v1"
    assert replay["failure_handling"]["status"] == "no_action_required"
    assert replay["manager_notes"]["schema_version"] == "agentic_csp.manager_notes.v1"
    assert replay["manager_notes"]["step_notes"][0]["decision"] == "continue"
    assert replay["tool_call_log_rows"][0]["schema_version"] == "agentic_csp.tool_call_log_row.v1"
    assert replay["tool_call_log_rows"][0]["execution_performed"] is False
    assert replay["manager_replay_artifacts"]["schema_version"] == (
        "agentic_csp.manager_replay_artifacts.v1"
    )
    assert replay["c_layer_replay_report"]["schema_version"] == "agentic_csp.c_layer_replay_report.v1"
    assert [item["name"] for item in replay["c_layer_replay_report"]["c_steps"]] == [
        "execution_intent",
        "execution_handoff",
        "executor_preflight",
        "step_execution_plan",
        "noop_step_execution",
        "result_inspection",
        "failure_handling",
        "manager_notes",
        "tool_call_log_rows",
        "manager_replay_artifacts",
        "partial_success",
        "continuation_summary",
    ]
    assert replay["c_layer_replay_report"]["final_status"] == "continue_allowed"
    assert replay["noop_execution_report"]["status"] == result["noop_execution_report"]["status"]
    assert replay["noop_execution_report"]["execution_performed"] is False
    assert manager_notes_path.exists()
    assert tool_call_log_path.exists()
    assert len(tool_call_log_rows) == len(replay["tool_call_log_rows"]) == 1
    assert all(row["execution_performed"] is False for row in tool_call_log_rows)
    assert tool_call_log_rows[0]["tool_name"] == "crystal.csp_pack"
    assert chain_json_path.exists()
    assert fixture_json_path.exists()
    assert chain_markdown_path.exists()
    assert all(Path(path).exists() for path in result["artifact_paths"])
    assert all(Path(paths["json"]).exists() for paths in result["trace_paths"].values())
    assert all(Path(paths["markdown"]).exists() for paths in result["trace_paths"].values())
    assert _find_unexpected_execution_artifacts(case_dir) == []

    # Verify partial_success and continuation_summary are present and have correct schema versions
    assert replay["partial_success"]["schema_version"] == "agentic_csp.partial_success.v1"
    assert replay["continuation_summary"]["schema_version"] == "agentic_csp.continuation_summary.v1"
    assert replay["partial_success"]["route_mode"] == "fixture_replay_c_layer"
    assert replay["partial_success"]["source_run_id"] == "run_001"
    assert replay["partial_success"]["status"] == "continue_allowed"
    assert len(replay["partial_success"]["continuation_plan"]) == 1
    assert replay["partial_success"]["blocked_dependencies"] == []
    assert replay["partial_success"]["optional_stages_skipped"] == []
    assert replay["partial_success"]["recovery_paths"] == []
    assert replay["partial_success"]["warnings"] == []

    # Verify continuation_summary has correct structure
    assert replay["continuation_summary"]["final_status"] == "continue_allowed"
    assert replay["continuation_summary"]["continued_steps"] == ["crystal.csp_pack"]
    assert replay["continuation_summary"]["skipped_steps"] == []
    assert replay["continuation_summary"]["blocked_steps"] == []
    assert replay["continuation_summary"]["recovery_steps"] == []
    assert replay["continuation_summary"]["summary_text"] == (
        "All replay steps remain eligible to continue."
    )

    # Print the new outputs for live verification
    print(f"AGENTIC_PARTIAL_SUCCESS={json.dumps(replay['partial_success'], sort_keys=True)}")
    print(f"AGENTIC_CONTINUATION_SUMMARY={json.dumps(replay['continuation_summary'], sort_keys=True)}")
