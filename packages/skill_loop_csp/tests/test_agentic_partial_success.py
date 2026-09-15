from __future__ import annotations

import ast
import inspect
import json
import sys
from copy import deepcopy

from sok_llm_orchestrator.agentic.chain_fixtures import replay_c_layer_from_fixture
from sok_llm_orchestrator.agentic.failure_handling import handle_inspection_failures
from sok_llm_orchestrator.agentic.partial_success import (
    build_continuation_summary,
    build_partial_success_evaluation,
)
from sok_llm_orchestrator.agentic.result_inspection import inspect_step_results
import sok_llm_orchestrator.agentic.partial_success as partial_success_module


def _base_fixture() -> dict[str, object]:
    compile_result = {
        "schema_version": "agentic_csp.plan_compile.v1",
        "proposals": [
            {
                "schema_version": "agentic_csp.tool_call_proposal.v1",
                "tool_name": "crystal.csp_pack",
                "arguments": {"case_id": "run_001", "objective_family": "retrieval"},
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
    }


def _rebuild_for_issue(
    metadata: dict[str, object],
    summary: str,
) -> dict[str, object]:
    replay = replay_c_layer_from_fixture(_base_fixture())
    updated = deepcopy(replay)
    updated["noop_step_execution"]["step_results"][0]["result_summary"] = summary
    updated["noop_step_execution"]["step_results"][0]["metadata"] = metadata
    updated["result_inspection"] = inspect_step_results(updated["noop_step_execution"])
    updated["failure_handling"] = handle_inspection_failures(updated["result_inspection"])
    updated["partial_success"] = build_partial_success_evaluation(updated)
    updated["continuation_summary"] = build_continuation_summary(updated["partial_success"])
    return updated


def test_partial_success_happy_path_continue_allowed() -> None:
    replay = replay_c_layer_from_fixture(_base_fixture())
    before = deepcopy(replay)

    partial = build_partial_success_evaluation(replay)
    summary = build_continuation_summary(partial)

    assert replay == before
    assert partial["schema_version"] == "agentic_csp.partial_success.v1"
    assert partial["route_mode"] == "fixture_replay_c_layer"
    assert partial["source_run_id"] == "run_001"
    assert partial["status"] == "continue_allowed"
    assert partial["blocked_dependencies"] == []
    assert partial["optional_stages_skipped"] == []
    assert partial["recovery_paths"] == []
    assert partial["continuation_plan"][0]["continuation_decision"] == "continue"
    assert summary["schema_version"] == "agentic_csp.continuation_summary.v1"
    assert summary["final_status"] == "continue_allowed"
    assert summary["continued_steps"] == ["crystal.csp_pack"]
    assert summary["skipped_steps"] == []
    assert summary["blocked_steps"] == []
    assert summary["recovery_steps"] == []


def test_partial_success_spp_blocked_uses_optional_skip_path() -> None:
    updated = _rebuild_for_issue({"spp_blocked": True}, "spp_blocked")

    assert updated["partial_success"]["status"] == "continue_with_warnings"
    assert updated["partial_success"]["optional_stages_skipped"] == ["crystal.csp_pack"]
    assert updated["partial_success"]["continuation_plan"][0]["continuation_decision"] == (
        "continue_optional_path"
    )
    assert updated["continuation_summary"]["final_status"] == "continue_with_warnings"
    assert updated["continuation_summary"]["skipped_steps"] == ["crystal.csp_pack"]


def test_partial_success_qlip_infeasible_uses_recovery_path() -> None:
    updated = _rebuild_for_issue({"qlip_infeasible": True}, "qlip_infeasible")

    assert updated["partial_success"]["status"] == "continue_with_warnings"
    assert updated["partial_success"]["recovery_paths"] == ["crystal.csp_pack"]
    assert updated["partial_success"]["continuation_plan"][0]["continuation_decision"] == (
        "recovery_required"
    )
    assert updated["continuation_summary"]["recovery_steps"] == ["crystal.csp_pack"]


def test_partial_success_no_exportable_structures_uses_recovery_path() -> None:
    updated = _rebuild_for_issue(
        {"no_exportable_structures": True},
        "no_exportable_structures",
    )

    assert updated["partial_success"]["status"] == "continue_with_warnings"
    assert updated["partial_success"]["recovery_paths"] == ["crystal.csp_pack"]
    assert updated["continuation_summary"]["recovery_steps"] == ["crystal.csp_pack"]


def test_partial_success_qlip_packaging_invalid_uses_recovery_path() -> None:
    replay = replay_c_layer_from_fixture(_base_fixture())
    replay["failure_handling"] = {
        "schema_version": "agentic_csp.failure_handling.v1",
        "status": "recovery_planned",
        "actions": [
            {
                "action_index": 0,
                "source_step_index": 3,
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
    }
    replay["partial_success"] = build_partial_success_evaluation(replay)
    replay["continuation_summary"] = build_continuation_summary(replay["partial_success"])

    assert replay["partial_success"]["status"] == "continue_with_warnings"
    assert replay["partial_success"]["recovery_paths"] == ["qlip.validate_request"]
    assert replay["continuation_summary"]["recovery_steps"] == ["qlip.validate_request"]


def test_partial_success_zero_cifs_blocks() -> None:
    updated = _rebuild_for_issue({"cif_count": 0}, "cif_count: 0")

    assert updated["partial_success"]["status"] == "blocked"
    assert updated["partial_success"]["blocked_dependencies"] == ["crystal.csp_pack"]
    assert updated["partial_success"]["continuation_plan"][0]["continuation_decision"] == "blocked"
    assert updated["continuation_summary"]["final_status"] == "blocked"
    assert updated["continuation_summary"]["blocked_steps"] == ["crystal.csp_pack"]


def test_partial_success_is_json_serializable_and_deterministic() -> None:
    replay = replay_c_layer_from_fixture(_base_fixture())

    first = build_partial_success_evaluation(replay)
    second = build_partial_success_evaluation(replay)
    summary_first = build_continuation_summary(first)
    summary_second = build_continuation_summary(first)

    assert first == second
    assert summary_first == summary_second
    assert json.loads(json.dumps(first))["status"] == "continue_allowed"
    assert json.loads(json.dumps(summary_first))["final_status"] == "continue_allowed"


def test_partial_success_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(partial_success_module)
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


def test_partial_success_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    assert "sok_llm_orchestrator.pipeline" not in sys.modules
