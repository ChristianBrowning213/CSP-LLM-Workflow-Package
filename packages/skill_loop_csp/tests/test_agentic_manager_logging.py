from __future__ import annotations

import ast
import inspect
import json
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from sok_llm_orchestrator.agentic.chain_fixtures import replay_c_layer_from_fixture
from sok_llm_orchestrator.agentic.failure_handling import handle_inspection_failures
from sok_llm_orchestrator.agentic.manager_logging import (
    build_manager_notes,
    build_tool_call_log_rows,
    write_manager_replay_artifacts,
)
from sok_llm_orchestrator.agentic.result_inspection import inspect_step_results
import sok_llm_orchestrator.agentic.manager_logging as manager_logging_module


def _repo_local_tempdir() -> Path:
    parent = Path.cwd() / "test_workdir" / "agentic_manager_logging_tmp"
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / f"case_{uuid4().hex}"
    path.mkdir()
    return path


def _base_chain_result() -> dict[str, object]:
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
    }


def _inject_issue(
    replay: dict[str, object],
    metadata: dict[str, object],
    summary: str,
) -> dict[str, object]:
    updated = deepcopy(replay)
    updated["noop_step_execution"]["step_results"][0]["result_summary"] = summary
    updated["noop_step_execution"]["step_results"][0]["metadata"] = metadata
    updated["result_inspection"] = inspect_step_results(updated["noop_step_execution"])
    updated["failure_handling"] = handle_inspection_failures(updated["result_inspection"])
    return updated


def test_build_manager_notes_clear_path_uses_continue_decision() -> None:
    replay = replay_c_layer_from_fixture(_base_chain_result())
    before = deepcopy(replay)

    notes = build_manager_notes(replay)
    rows = build_tool_call_log_rows(replay)

    assert replay == before
    assert notes["schema_version"] == "agentic_csp.manager_notes.v1"
    assert notes["step_notes"][0]["tool_name"] == "crystal.csp_pack"
    assert notes["step_notes"][0]["decision"] == "continue"
    assert notes["step_notes"][0]["failure_action"] == "continue"
    assert notes["step_notes"][0]["inspection_status"] == "clear"
    assert notes["step_notes"][0]["step_input_summary"]["proposed_arguments"] == {
        "case_id": "run_001",
        "objective_family": "retrieval",
    }
    assert notes["step_notes"][0]["step_output_summary"]["result_summary"] == "noop dry run only"
    assert rows[0]["execution_performed"] is False
    assert rows[0]["decision"] == "continue"
    assert json.loads(json.dumps(notes))["source_run_id"] == "run_001"


def test_build_manager_notes_zero_cif_path_uses_block_decision() -> None:
    replay = _inject_issue(
        replay_c_layer_from_fixture(_base_chain_result()),
        {"cif_count": 0},
        "cif_count: 0",
    )

    notes = build_manager_notes(replay)
    rows = build_tool_call_log_rows(replay)

    assert notes["step_notes"][0]["decision"] == "block"
    assert notes["step_notes"][0]["failure_action"] == "block_next_stage"
    assert rows[0]["failure_action"] == "block_next_stage"
    assert rows[0]["decision"] == "block"


def test_build_manager_notes_qlip_infeasible_path_uses_recover_decision() -> None:
    replay = _inject_issue(
        replay_c_layer_from_fixture(_base_chain_result()),
        {"qlip_infeasible": True},
        "qlip_infeasible",
    )

    notes = build_manager_notes(replay)
    rows = build_tool_call_log_rows(replay)

    assert notes["step_notes"][0]["decision"] == "recover"
    assert notes["step_notes"][0]["failure_action"] == "recompile_request"
    assert rows[0]["decision"] == "recover"


def test_build_manager_notes_no_exportable_structures_uses_recover_decision() -> None:
    replay = _inject_issue(
        replay_c_layer_from_fixture(_base_chain_result()),
        {"no_exportable_structures": True},
        "no_exportable_structures",
    )

    notes = build_manager_notes(replay)
    rows = build_tool_call_log_rows(replay)

    assert notes["step_notes"][0]["decision"] == "recover"
    assert notes["step_notes"][0]["failure_action"] == "fallback_retrieval"
    assert rows[0]["failure_action"] == "fallback_retrieval"


def test_build_manager_notes_spp_blocked_uses_skip_decision() -> None:
    replay = _inject_issue(
        replay_c_layer_from_fixture(_base_chain_result()),
        {"spp_blocked": True},
        "spp_blocked",
    )

    notes = build_manager_notes(replay)
    rows = build_tool_call_log_rows(replay)

    assert notes["step_notes"][0]["decision"] == "skip"
    assert notes["step_notes"][0]["failure_action"] == "skip_optional_stage"
    assert rows[0]["decision"] == "skip"


def test_write_manager_replay_artifacts_writes_json_and_jsonl_round_trip() -> None:
    replay = replay_c_layer_from_fixture(_base_chain_result())
    before = deepcopy(replay)
    root = _repo_local_tempdir()
    try:
        write_result = write_manager_replay_artifacts(replay, root)
        manager_notes_path = Path(write_result["manager_notes_path"])
        tool_call_log_path = Path(write_result["tool_call_log_path"])

        manager_notes = json.loads(manager_notes_path.read_text(encoding="utf-8"))
        rows = [
            json.loads(line)
            for line in tool_call_log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        file_names = sorted(path.name for path in root.iterdir())

        assert replay == before
        assert write_result["schema_version"] == "agentic_csp.manager_replay_artifacts.v1"
        assert manager_notes["schema_version"] == "agentic_csp.manager_notes.v1"
        assert rows[0]["schema_version"] == "agentic_csp.tool_call_log_row.v1"
        assert rows[0]["execution_performed"] is False
        assert len(rows) == len(manager_notes["step_notes"]) == 1
        assert file_names == ["manager_notes.json", "tool_call_log.jsonl"]
        assert all(not name.startswith(".") for name in file_names)
        assert all(not name.endswith(".db") for name in file_names)
        assert all(not name.endswith(".sqlite") for name in file_names)
    finally:
        if root.exists():
            shutil.rmtree(root)


def test_manager_logging_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(manager_logging_module)
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


def test_manager_logging_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    assert "sok_llm_orchestrator.pipeline" not in sys.modules
