from __future__ import annotations

import ast
import inspect
import json
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from sok_llm_orchestrator.agentic.chain_fixtures import (
    C_LAYER_REPLAY_SCHEMA_VERSION,
    assert_chain_fixture_ready_for_c_layer,
    build_c_layer_replay_report,
    load_chain_fixture,
    replay_c_layer_from_fixture,
    write_chain_fixture,
)
import sok_llm_orchestrator.agentic.chain_fixtures as chain_fixtures_module


def _repo_local_tempdir() -> Path:
    parent = Path.cwd() / "test_workdir" / "agentic_chain_fixtures_tmp"
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / f"case_{uuid4().hex}"
    path.mkdir()
    return path


def _chain_result() -> dict[str, object]:
    compile_result = {
        "schema_version": "agentic_csp.plan_compile.v1",
        "proposals": [
            {
                "schema_version": "agentic_csp.tool_call_proposal.v1",
                "tool_name": "crystal.csp_pack",
                "arguments": {
                    "case_id": "run_001",
                    "objective_family": "retrieval",
                },
                "expected_result": "Ranked candidate set with exportability metadata.",
            }
        ],
        "validation_results": [
            {
                "schema_version": "agentic_csp.tool_validation.v1",
                "tool_name": "crystal.csp_pack",
                "valid": True,
                "errors": [],
                "warnings": [],
            }
        ],
        "warnings": [],
    }
    return {
        "schema_version": "agentic_csp.proposal_review_chain.v1",
        "run_id": "run_001",
        "route_mode": "full_live_agent_chain",
        "planner_result": {
            "schema_version": "agentic_csp.planner_compile_run.v1",
            "run_plan": {
                "schema_version": "agentic_csp.run_plan.v1",
                "overall_goal": "TiO2",
                "run_goal": "retrieve candidates",
                "stage": "wide_exploration",
                "plan_as_text": "tool_hint: crystal.csp_pack",
            },
            "compile_result": compile_result,
            "proposal_count": 1,
            "valid_proposal_count": 1,
            "invalid_proposal_count": 0,
            "warnings": [],
        },
        "compile_result": compile_result,
        "run_manager_log": {
            "schema_version": "agentic_csp.run_manager_log.v1",
            "run_id": "run_001",
            "tool_calls_attempted": [],
            "manager_notes": "Reviewed proposal readiness only; no execution occurred.",
            "failures_handled": [],
            "artifacts_created": [],
        },
        "run_evaluation": {
            "schema_version": "agentic_csp.run_evaluation.v1",
            "run_id": "run_001",
            "run_goal": "retrieve candidates",
            "run_goal_success": True,
            "overall_goal_progress": "Proposal review advanced the overall goal without execution.",
            "summary": "Review-only run produced a valid future proposal.",
            "what_worked": ["Compilable tool hint emitted."],
            "what_failed_or_was_weak": ["No execution occurred."],
            "scientific_findings": ["Proposal readiness improved."],
            "best_artifacts": [],
            "scores": {"proposal_readiness": "good"},
            "comparison_to_previous_best": "Comparable to prior review-only runs.",
            "recommended_next_run": "Continue proposal review.",
            "should_stop": False,
            "stop_reason": "",
            "needs_user_clarification": False,
            "clarification_question": "",
        },
        "orchestrator_decision": {
            "schema_version": "agentic_csp.orchestrator_decision.v1",
            "decision": "continue",
            "reason": "The evaluator reports a useful proposal-review run.",
            "next_run_goal": "Continue proposal review.",
            "current_stage": "wide_exploration",
            "evidence_used": ["run_evaluation", "run_manager_log", "compile_result"],
            "user_message_if_stopping": "",
            "clarification_question_if_needed": "",
        },
        "trace_paths": {
            "planner": {
                "json": "planner/agentic_llm_trace_planner.json",
                "markdown": "planner/agentic_llm_trace_planner.md",
            }
        },
    }


def test_write_and_load_chain_fixture_round_trips_exactly() -> None:
    chain_result = _chain_result()
    before = deepcopy(chain_result)
    root = _repo_local_tempdir()
    try:
        write_result = write_chain_fixture(chain_result, root)
        loaded = load_chain_fixture(write_result["fixture_json_path"])

        assert chain_result == before
        assert loaded == before
        assert Path(write_result["fixture_json_path"]).exists()
        assert json.loads(json.dumps(loaded))["run_id"] == "run_001"
    finally:
        if root.exists():
            shutil.rmtree(root)


def test_assert_chain_fixture_ready_for_c_layer_fails_when_required_fields_missing() -> None:
    broken = _chain_result()
    del broken["run_evaluation"]

    with pytest.raises(ValueError, match="Missing required A/B chain mappings"):
        assert_chain_fixture_ready_for_c_layer(broken)


def test_replay_c_layer_from_fixture_recomputes_c_outputs_deterministically() -> None:
    chain_result = _chain_result()
    before = deepcopy(chain_result)
    root = _repo_local_tempdir()

    replay = replay_c_layer_from_fixture(chain_result, write_manager_artifacts_dir=root)

    assert chain_result == before
    assert replay["schema_version"] == C_LAYER_REPLAY_SCHEMA_VERSION
    assert replay["route_mode"] == "fixture_replay_c_layer"
    assert replay["source_chain_schema_version"] == "agentic_csp.proposal_review_chain.v1"
    assert replay["source_run_id"] == "run_001"
    assert replay["execution_intent"]["status"] == "ready_for_execution"
    assert replay["execution_handoff"]["status"] == "ready"
    assert replay["executor_preflight"]["status"] == "blocked"
    assert replay["step_execution_plan"]["schema_version"] == "agentic_csp.step_execution_plan.v1"
    assert replay["step_execution_plan"]["status"] == "ready"
    assert replay["step_execution_plan"]["steps"][0]["tool_name"] == "crystal.csp_pack"
    assert replay["step_execution_plan"]["steps"][0]["status"] == "pending"
    assert replay["noop_step_execution"]["schema_version"] == "agentic_csp.noop_step_execution.v1"
    assert replay["noop_step_execution"]["status"] == "completed"
    assert replay["noop_step_execution"]["execution_performed"] is False
    assert replay["noop_step_execution"]["step_results"][0]["tool_name"] == "crystal.csp_pack"
    assert replay["noop_step_execution"]["step_results"][0]["status"] == "would_execute"
    assert replay["result_inspection"]["schema_version"] == "agentic_csp.result_inspection.v1"
    assert replay["result_inspection"]["status"] == "clear"
    assert replay["result_inspection"]["inspected_steps"][0]["tool_name"] == "crystal.csp_pack"
    assert replay["result_inspection"]["inspected_steps"][0]["inspection_status"] == "clear"
    assert replay["result_inspection"]["inspected_steps"][0]["recommended_action"] == "continue"
    assert replay["failure_handling"]["schema_version"] == "agentic_csp.failure_handling.v1"
    assert replay["failure_handling"]["status"] == "no_action_required"
    assert replay["failure_handling"]["actions"][0]["action_type"] == "continue"
    assert replay["noop_execution_report"]["status"] == "blocked"
    assert replay["noop_execution_report"]["execution_performed"] is False
    assert replay["noop_execution_report"]["dry_run_only"] is True
    assert replay["c_layer_replay_report"]["schema_version"] == "agentic_csp.c_layer_replay_report.v1"
    assert replay["c_layer_replay_report"]["route_mode"] == "fixture_replay_c_layer"
    assert replay["c_layer_replay_report"]["final_status"] == "continue_allowed"
    assert replay["replay_steps"] == [
        "execution_intent",
        "execution_handoff",
        "executor_preflight",
        "step_execution_plan",
        "noop_step_execution",
        "result_inspection",
        "failure_handling",
        "noop_execution_report",
        "manager_notes",
        "tool_call_log_rows",
        "manager_replay_artifacts",
        "partial_success",
        "continuation_summary",
    ]
    assert replay["warnings"] == []
    assert json.loads(json.dumps(replay))["route_mode"] == "fixture_replay_c_layer"

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


def test_replay_c_layer_from_fixture_can_write_manager_artifacts() -> None:
    chain_result = _chain_result()
    root = _repo_local_tempdir()
    try:
        replay = replay_c_layer_from_fixture(
            chain_result,
            write_manager_artifacts_dir=root,
        )
        manager_notes_path = Path(
            replay["manager_replay_artifacts"]["manager_notes_path"]
        )
        tool_call_log_path = Path(
            replay["manager_replay_artifacts"]["tool_call_log_path"]
        )
        tool_call_log_rows = [
            json.loads(line)
            for line in tool_call_log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        assert replay["manager_notes"]["schema_version"] == "agentic_csp.manager_notes.v1"
        assert replay["manager_notes"]["step_notes"][0]["decision"] == "continue"
        assert replay["tool_call_log_rows"][0]["schema_version"] == "agentic_csp.tool_call_log_row.v1"
        assert replay["tool_call_log_rows"][0]["execution_performed"] is False
        assert replay["manager_replay_artifacts"]["schema_version"] == (
            "agentic_csp.manager_replay_artifacts.v1"
        )
        assert manager_notes_path.exists()
        assert tool_call_log_path.exists()
        assert len(tool_call_log_rows) == len(replay["tool_call_log_rows"]) == 1
        assert tool_call_log_rows[0]["tool_name"] == "crystal.csp_pack"
        assert replay["replay_steps"][-3:] == [
            "manager_replay_artifacts",
            "partial_success",
            "continuation_summary",
        ]
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
    finally:
        if root.exists():
            shutil.rmtree(root)


def test_build_c_layer_replay_report_can_be_called_directly() -> None:
    replay = replay_c_layer_from_fixture(_chain_result())
    report = build_c_layer_replay_report(replay)

    assert report["schema_version"] == "agentic_csp.c_layer_replay_report.v1"
    assert report["route_mode"] == "fixture_replay_c_layer"
    assert report["final_status"] == "continue_allowed"


def test_chain_fixtures_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(chain_fixtures_module)
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


def test_chain_fixtures_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    assert "sok_llm_orchestrator.pipeline" not in sys.modules
