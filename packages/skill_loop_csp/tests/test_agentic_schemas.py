from __future__ import annotations

import ast
import importlib
import inspect
import json
import sys
from pathlib import Path

from sok_llm_orchestrator.agentic.schemas import (
    AGENT_INPUT_SCHEMA_VERSION,
    ORCHESTRATOR_DECISION_SCHEMA_VERSION,
    RUN_EVALUATION_SCHEMA_VERSION,
    RUN_MANAGER_LOG_SCHEMA_VERSION,
    RUN_PLAN_SCHEMA_VERSION,
    TOOL_CALL_PROPOSAL_SCHEMA_VERSION,
    AgentInputEnvelope,
    OrchestratorDecision,
    RunEvaluation,
    RunManagerLog,
    RunPlan,
    ToolCallProposal,
    assert_json_serializable,
    to_json_dict,
)
import sok_llm_orchestrator.agentic.schemas as schema_module


def test_schema_objects_construct_and_serialize_to_json() -> None:
    envelope = AgentInputEnvelope(
        agent_name="planner",
        payload={"task": "band-gap search", "budget": 3},
        context_summary={"stage": "planning", "previous_runs": 1},
        artifact_refs=[{"artifact_id": "brief.md", "kind": "markdown"}],
    )
    proposal = ToolCallProposal(
        step="summarize prior run outputs",
        tool_name="artifact_reader",
        arguments={"artifact_id": "run-001/report.json"},
        expected_result="A compact summary of earlier findings.",
        why="Planner context should be grounded in existing artifacts.",
        condition="Only if the artifact exists in the run archive.",
    )
    plan = RunPlan(
        overall_goal="Improve band gap benchmark performance.",
        run_goal="Draft the next archive-ready experiment strategy.",
        stage="planning",
        detailed_description="Summarize the next run in durable plain-language terms.",
        hoping_to_find="A better direction for the next candidate run.",
        plan_as_text="Review prior outcomes and propose a narrower next run goal.",
        what_we_tried_previously_that_is_related="A baseline sweep over candidate structures.",
        success_criteria=["Clear next-run strategy", "Archive-ready summary"],
        stop_conditions_for_this_run=["Missing evidence", "Goal already satisfied"],
    )
    manager_log = RunManagerLog(
        run_id="run-002",
        tool_calls_attempted=[proposal],
        failures_handled=["No tool execution in A2-prep; proposal recorded only."],
        manager_notes="Tool proposals are recorded without execution.",
        artifacts_created=[{"path": "artifacts/run-002/proposals.json", "kind": "json"}],
    )
    evaluation = RunEvaluation(
        run_id="run-002",
        run_goal="Draft the next archive-ready experiment strategy.",
        run_goal_success=True,
        overall_goal_progress="Progressed from broad search framing to a narrower strategy.",
        summary="The run produced a reusable planning artifact.",
        what_worked=["Concise strategy text", "Clear stop conditions"],
        what_failed_or_was_weak=["No runtime execution yet"],
        scientific_findings=["Prior work suggests narrowing the composition search space."],
        best_artifacts=[{"path": "artifacts/run-002/plan.json", "kind": "json"}],
        scores={"strategy_clarity": 0.9, "archive_readiness": 1.0},
        comparison_to_previous_best="More specific than the previous planning draft.",
        recommended_next_run="Convert the plan into structured tool proposals.",
        should_stop=False,
        stop_reason=None,
        needs_user_clarification=False,
        clarification_question=None,
    )
    decision = OrchestratorDecision(
        decision="continue",
        reason="A concrete next run goal is available.",
        next_run_goal="Convert the plan into structured tool proposals.",
        current_stage="orchestration",
        evidence_used=["run-002 evaluation", "plan.json"],
        user_message_if_stopping=None,
        clarification_question_if_needed=None,
    )

    objects = [envelope, proposal, plan, manager_log, evaluation, decision]

    for obj in objects:
        data = to_json_dict(obj)
        assert isinstance(data, dict)
        assert_json_serializable(obj)
        decoded = json.loads(json.dumps(data))
        assert decoded["schema_version"] == data["schema_version"]


def test_schema_versions_match_expected_constants() -> None:
    assert AgentInputEnvelope().schema_version == AGENT_INPUT_SCHEMA_VERSION
    assert RunPlan().schema_version == RUN_PLAN_SCHEMA_VERSION
    assert ToolCallProposal().schema_version == TOOL_CALL_PROPOSAL_SCHEMA_VERSION
    assert RunManagerLog().schema_version == RUN_MANAGER_LOG_SCHEMA_VERSION
    assert RunEvaluation().schema_version == RUN_EVALUATION_SCHEMA_VERSION
    assert OrchestratorDecision().schema_version == ORCHESTRATOR_DECISION_SCHEMA_VERSION


def test_list_and_dict_fields_preserve_content() -> None:
    proposal = ToolCallProposal(
        step="inspect artifacts",
        tool_name="artifact_reader",
        arguments={"paths": ["a.json", "b.json"], "limit": 2},
        expected_result="A joined summary.",
        why="The next plan should cite earlier outputs.",
        condition="Only when artifacts are present.",
    )
    manager_log = RunManagerLog(
        run_id="run-100",
        tool_calls_attempted=[proposal],
        failures_handled=["none"],
        manager_notes="placeholder",
        artifacts_created=[{"path": "artifacts/run-100/log.json", "kind": "json"}],
    )
    evaluation = RunEvaluation(
        run_id="run-100",
        run_goal="Inspect previous artifacts.",
        run_goal_success=False,
        overall_goal_progress="Partial",
        summary="More evidence needed.",
        what_worked=["artifact list compiled"],
        what_failed_or_was_weak=["no scoring evidence"],
        scientific_findings=["none yet"],
        best_artifacts=[{"path": "artifacts/run-100/log.json", "kind": "json"}],
        scores={"confidence": 0.25, "notes": {"source_count": 2}},
        comparison_to_previous_best="Not yet better.",
        recommended_next_run="Gather more evidence.",
        should_stop=False,
        stop_reason=None,
        needs_user_clarification=True,
        clarification_question="Which benchmark target should we prioritize first?",
    )

    manager_data = to_json_dict(manager_log)
    evaluation_data = to_json_dict(evaluation)

    assert manager_data["tool_calls_attempted"][0]["arguments"]["paths"] == ["a.json", "b.json"]
    assert manager_data["artifacts_created"][0]["path"] == "artifacts/run-100/log.json"
    assert evaluation_data["scores"]["notes"]["source_count"] == 2
    assert evaluation_data["best_artifacts"][0]["kind"] == "json"


def test_importing_schemas_does_not_import_pipeline_code() -> None:
    importlib.import_module("sok_llm_orchestrator.agentic.schemas")
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules


def test_agentic_package_has_no_sqlite_dependency() -> None:
    package_dir = Path(schema_module.__file__).resolve().parent
    imported_modules: set[str] = set()

    for path in package_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name.split(".")[0] for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.add(node.module.split(".")[0])

    assert "sqlite3" not in imported_modules
    assert "sqlalchemy" not in imported_modules


def test_schema_module_has_no_pipeline_imports() -> None:
    source = inspect.getsource(schema_module)
    tree = ast.parse(source)
    imported_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)

    assert "sok_llm_orchestrator.orchestrator.pipeline" not in imported_modules
