from __future__ import annotations

from copy import deepcopy

from sok_llm_orchestrator.agentic.chain_fixtures import (
    build_c_layer_replay_report,
    replay_c_layer_from_fixture,
)
from sok_llm_orchestrator.agentic.failure_handling import handle_inspection_failures
from sok_llm_orchestrator.agentic.result_inspection import inspect_step_results


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


def _inject_issue(replay: dict[str, object], metadata: dict[str, object], summary: str = "noop dry run only") -> dict[str, object]:
    altered = deepcopy(replay)
    altered["noop_step_execution"]["step_results"][0]["result_summary"] = summary
    altered["noop_step_execution"]["step_results"][0]["metadata"] = metadata
    altered["result_inspection"] = inspect_step_results(altered["noop_step_execution"])
    altered["failure_handling"] = handle_inspection_failures(altered["result_inspection"])
    from sok_llm_orchestrator.agentic.partial_success import (
        build_continuation_summary,
        build_partial_success_evaluation,
    )

    altered["partial_success"] = build_partial_success_evaluation(altered)
    altered["continuation_summary"] = build_continuation_summary(altered["partial_success"])
    altered["c_layer_replay_report"] = build_c_layer_replay_report(altered)
    return altered


def test_c_layer_replay_happy_path_report_contains_all_steps_in_order() -> None:
    replay = replay_c_layer_from_fixture(_base_fixture())
    report = replay["c_layer_replay_report"]

    assert replay["failure_handling"]["status"] == "no_action_required"
    assert replay["partial_success"]["status"] == "continue_allowed"
    assert replay["continuation_summary"]["final_status"] == "continue_allowed"
    assert [item["name"] for item in report["c_steps"]] == [
        "execution_intent",
        "execution_handoff",
        "executor_preflight",
        "step_execution_plan",
        "noop_step_execution",
        "result_inspection",
        "failure_handling",
        "partial_success",
        "continuation_summary",
    ]
    assert report["final_status"] == "continue_allowed"


def test_c_layer_replay_zero_cif_path_blocks_next_stage() -> None:
    replay = replay_c_layer_from_fixture(_base_fixture())
    altered = _inject_issue(replay, {"cif_count": 0})

    assert altered["result_inspection"]["status"] == "blocked"
    assert altered["failure_handling"]["status"] == "blocked"
    assert altered["failure_handling"]["actions"][0]["action_type"] == "block_next_stage"
    assert altered["partial_success"]["status"] == "blocked"
    assert altered["continuation_summary"]["final_status"] == "blocked"


def test_c_layer_replay_qlip_infeasible_path_recommends_recompile() -> None:
    replay = replay_c_layer_from_fixture(_base_fixture())
    altered = _inject_issue(replay, {"qlip_infeasible": True})

    assert altered["result_inspection"]["status"] == "recovery_recommended"
    assert altered["failure_handling"]["status"] == "recovery_planned"
    assert altered["failure_handling"]["actions"][0]["action_type"] == "recompile_request"
    assert altered["partial_success"]["status"] == "continue_with_warnings"
    assert altered["continuation_summary"]["recovery_steps"] == ["crystal.csp_pack"]


def test_c_layer_replay_no_exportable_structures_path_recommends_fallback() -> None:
    replay = replay_c_layer_from_fixture(_base_fixture())
    altered = _inject_issue(replay, {"no_exportable_structures": True})

    assert altered["failure_handling"]["status"] == "recovery_planned"
    assert altered["failure_handling"]["actions"][0]["action_type"] == "fallback_retrieval"
    assert altered["partial_success"]["status"] == "continue_with_warnings"


def test_c_layer_replay_spp_blocked_path_recommends_skip_optional_stage() -> None:
    replay = replay_c_layer_from_fixture(_base_fixture())
    altered = _inject_issue(replay, {"spp_blocked": True})

    assert altered["failure_handling"]["status"] == "recovery_planned"
    assert altered["failure_handling"]["actions"][0]["action_type"] == "skip_optional_stage"
    assert altered["partial_success"]["status"] == "continue_with_warnings"
    assert altered["continuation_summary"]["skipped_steps"] == ["crystal.csp_pack"]
