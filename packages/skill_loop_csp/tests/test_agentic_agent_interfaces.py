from __future__ import annotations

import ast
import inspect
import json
import sys
from copy import deepcopy
from types import MappingProxyType

from sok_llm_orchestrator.agentic import (
    Agent,
    EvaluatorAgent,
    OrchestratorAgent,
    PlannerAgent,
    RunManagerAgent,
)
from sok_llm_orchestrator.agentic.schemas import (
    ORCHESTRATOR_DECISION_SCHEMA_VERSION,
    RUN_EVALUATION_SCHEMA_VERSION,
    RUN_MANAGER_LOG_SCHEMA_VERSION,
    RUN_PLAN_SCHEMA_VERSION,
)
import sok_llm_orchestrator.agentic.agents as agent_module


AGENT_TYPES = (
    (
        PlannerAgent,
        RUN_PLAN_SCHEMA_VERSION,
        {
            "overall_goal",
            "run_goal",
            "stage",
            "detailed_description",
            "hoping_to_find",
            "plan_as_text",
            "what_we_tried_previously_that_is_related",
            "success_criteria",
            "stop_conditions_for_this_run",
        },
    ),
    (
        RunManagerAgent,
        RUN_MANAGER_LOG_SCHEMA_VERSION,
        {
            "run_id",
            "tool_calls_attempted",
            "failures_handled",
            "manager_notes",
            "artifacts_created",
        },
    ),
    (
        EvaluatorAgent,
        RUN_EVALUATION_SCHEMA_VERSION,
        {
            "run_id",
            "run_goal",
            "run_goal_success",
            "overall_goal_progress",
            "summary",
            "what_worked",
            "what_failed_or_was_weak",
            "scientific_findings",
            "best_artifacts",
            "scores",
            "comparison_to_previous_best",
            "recommended_next_run",
            "should_stop",
            "stop_reason",
            "needs_user_clarification",
            "clarification_question",
        },
    ),
    (
        OrchestratorAgent,
        ORCHESTRATOR_DECISION_SCHEMA_VERSION,
        {
            "decision",
            "reason",
            "next_run_goal",
            "current_stage",
            "evidence_used",
            "user_message_if_stopping",
            "clarification_question_if_needed",
        },
    ),
)


def test_agents_can_be_instantiated_with_name_and_role() -> None:
    for agent_type, _, _ in AGENT_TYPES:
        agent = agent_type()
        assert isinstance(agent, Agent)
        assert isinstance(agent.name, str)
        assert agent.name
        assert isinstance(agent.role, str)
        assert agent.role


def test_agents_accept_dict_like_input_and_return_schema_backed_dict() -> None:
    payload = MappingProxyType(
        {
            "overall_goal": "Improve a benchmark-aligned target.",
            "run_goal": "Prepare the next deterministic planning artifact.",
            "stage": "planning",
            "run_id": "run-007",
        }
    )
    for agent_type, schema_version, required_fields in AGENT_TYPES:
        agent = agent_type()
        result = agent.run(payload)
        assert isinstance(result, dict)
        assert result["schema_version"] == schema_version
        assert required_fields.issubset(result.keys())


def test_planner_agent_output_uses_run_plan_schema() -> None:
    result = PlannerAgent().run({"overall_goal": "Improve stability", "run_goal": "Write plan"})
    assert result["schema_version"] == RUN_PLAN_SCHEMA_VERSION
    assert result["overall_goal"] == "Improve stability"
    assert result["run_goal"] == "Write plan"
    assert isinstance(result["success_criteria"], list)
    assert "tool_hint: crystal.csp_pack" in result["plan_as_text"]
    assert "retrieve or discover candidate crystal structures" in result["plan_as_text"]
    assert "ranked candidate set with exportability metadata" in result["plan_as_text"]


def test_run_manager_agent_output_uses_run_manager_log_schema() -> None:
    result = RunManagerAgent().run({"run_goal": "Prepare proposals", "run_id": "run-010"})
    assert result["schema_version"] == RUN_MANAGER_LOG_SCHEMA_VERSION
    assert result["run_id"] == "run-010"
    assert isinstance(result["tool_calls_attempted"], list)
    assert result["tool_calls_attempted"][0]["tool_name"] == "crystal.csp_pack"
    assert result["tool_calls_attempted"][0]["arguments"]["case_id"] == "run-010"


def test_evaluator_agent_output_uses_run_evaluation_schema() -> None:
    result = EvaluatorAgent().run({"run_goal": "Evaluate placeholder run", "run_id": "run-011"})
    assert result["schema_version"] == RUN_EVALUATION_SCHEMA_VERSION
    assert result["run_id"] == "run-011"
    assert result["run_goal"] == "Evaluate placeholder run"
    assert result["should_stop"] is False


def test_orchestrator_agent_output_uses_decision_schema() -> None:
    result = OrchestratorAgent().run(
        {
            "run_goal": "Plan the next run",
            "stage": "orchestration",
            "proposal_readiness": {
                "schema_version": "agentic_csp.proposal_readiness.v1",
                "status": "all_valid",
                "reason": "All validated tool proposals are ready for a future execution layer.",
                "can_execute_later": True,
            },
            "tool_validation_summary": {
                "proposal_count": 1,
                "valid_count": 1,
                "invalid_count": 0,
                "warning_count": 0,
                "valid_tool_names": ["crystal.csp_pack"],
                "invalid_tool_names": [],
            },
        }
    )
    assert result["schema_version"] == ORCHESTRATOR_DECISION_SCHEMA_VERSION
    assert result["decision"] == "continue"
    assert result["next_run_goal"] == "Plan the next run"
    assert result["current_stage"] == "orchestration"
    assert "allowed by current tool validation" in result["reason"]
    assert "proposals=1" in result["reason"]
    assert "valid=1" in result["reason"]
    assert "invalid=0" in result["reason"]
    assert "warnings=0" in result["reason"]
    assert "tool_validation_summary" in result["evidence_used"]


def test_agents_are_deterministic_and_side_effect_free() -> None:
    payload = {
        "overall_goal": "Advance the benchmark objective.",
        "run_goal": "Prepare the next schema-backed output.",
        "stage": "evaluation",
        "run_id": "run-099",
        "nested": {"beta": 2},
    }
    payload_before = deepcopy(payload)

    for agent_type, _, _ in AGENT_TYPES:
        agent = agent_type()
        first = agent.run(payload)
        second = agent.run(payload)
        assert first == second
        json.loads(json.dumps(first))

    assert payload == payload_before


def test_agent_outputs_are_json_serializable() -> None:
    payload = {"run_goal": "Prepare outputs", "run_id": "run-serial"}
    for agent_type, _, _ in AGENT_TYPES:
        result = agent_type().run(payload)
        encoded = json.dumps(result)
        decoded = json.loads(encoded)
        assert decoded["schema_version"] == result["schema_version"]


def test_agentic_layer_does_not_invoke_pipeline_code_path() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    _ = PlannerAgent().run({"task": "agentic"})
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules


def test_agentic_layer_has_no_sqlite_dependency() -> None:
    source = inspect.getsource(agent_module)
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
