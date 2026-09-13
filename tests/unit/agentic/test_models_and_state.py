from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from llm_csp.agentic.budgets import AgentBudgets, BudgetResource
from llm_csp.agentic.approvals import ApprovalRequest
from llm_csp.agentic.models import (
    ActorRole,
    AgentPlan,
    ApprovalCategory,
    ArtifactReference,
    ConstraintKind,
    ConstraintRecord,
    DecisionRecord,
    EvaluationCriterionResult,
    EvaluationRecord,
    EvaluationStatus,
    ParsedIntent,
    PlanStep,
    PlanStepStatus,
    RepairRecommendation,
    RepairType,
    ToolCall,
    ToolCallStatus,
    WorkflowRunReference,
)
from llm_csp.agentic.state import (
    AGENT_STATE_SCHEMA_VERSION,
    AgentRunState,
    WriteScope,
    new_identifier,
    utc_now_iso,
)
from llm_csp.agentic.termination import AgentRunStatus, is_terminal, transition_plan_step, transition_tool_call


FIXTURE = Path(__file__).parents[2] / "fixtures" / "agentic" / "canonical_agent_state.v1.json"


def _minimal_state(**updates) -> AgentRunState:
    intent = ParsedIntent("find a candidate")
    plan = AgentPlan("plan_1", "find a candidate", (PlanStep("step_1", "inspect_run", "inspect", {}),))
    values = {"agent_run_id": "agent_1", "user_goal": "find a candidate", "parsed_intent": intent, "plan": plan}
    values.update(updates)
    return AgentRunState(**values)


def test_status_and_terminal_semantics_are_closed() -> None:
    assert not is_terminal(AgentRunStatus.PENDING)
    assert not is_terminal(AgentRunStatus.RUNNING)
    assert all(is_terminal(status) for status in AgentRunStatus if status not in {AgentRunStatus.PENDING, AgentRunStatus.RUNNING})
    with pytest.raises(TypeError):
        is_terminal("SUCCESS")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        AgentRunStatus("invented")


def test_plan_round_trip_and_immutable_inputs() -> None:
    plan = _minimal_state().plan
    assert AgentPlan.from_dict(plan.to_dict()) == plan
    with pytest.raises(TypeError):
        plan.steps[0].inputs["shell"] = "no"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        plan.goal = "changed"  # type: ignore[misc]


def test_plan_rejects_unknown_tool_and_dependency() -> None:
    with pytest.raises(ValueError):
        PlanStep("step", "run_shell", "bad", {})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="known step"):
        AgentPlan("plan", "goal", (PlanStep("step", "inspect_run", "inspect", {}, ("missing",)),))
    with pytest.raises(ValueError, match="acyclic"):
        AgentPlan("plan", "goal", (
            PlanStep("one", "inspect_run", "one", {}, ("two",)),
            PlanStep("two", "inspect_run", "two", {}, ("one",)),
        ))
    with pytest.raises(ValueError, match="required_approvals"):
        AgentPlan("plan", "goal", (
            PlanStep("step", "inspect_run", "inspect", {}, approval_category=ApprovalCategory.EXPAND_SEARCH_SPACE),
        ))


def test_decision_requires_utc_and_concise_audit_rationale() -> None:
    with pytest.raises(ValueError, match="UTC"):
        DecisionRecord("d", ActorRole.PLANNER, "plan", "short", (), "2026-01-01T12:00:00")
    with pytest.raises(ValueError, match="concise"):
        DecisionRecord("d", ActorRole.PLANNER, "plan", "x" * 501, (), "2026-01-01T12:00:00Z")


def test_canonical_state_fixture_round_trips_deterministically() -> None:
    state = AgentRunState.from_json(FIXTURE.read_text(encoding="utf-8"))
    rebuilt = AgentRunState.from_json(state.to_json())
    assert rebuilt == state
    assert rebuilt.schema_version == AGENT_STATE_SCHEMA_VERSION
    assert rebuilt.workflow_runs[0].result_status == "OPTIMAL"


def test_state_rejects_unknown_schema_field() -> None:
    payload = _minimal_state().to_dict() | {"hidden_memory": {}}
    with pytest.raises(TypeError, match="unexpected"):
        AgentRunState.from_dict(payload)


def test_constraint_kinds_remain_distinct() -> None:
    records = tuple(ConstraintRecord(kind, kind.value) for kind in ConstraintKind)
    intent = ParsedIntent("goal", constraints=records)
    assert {item.kind for item in ParsedIntent.from_dict(intent.to_dict()).constraints} == set(ConstraintKind)


def test_repair_and_evaluation_contract_round_trip() -> None:
    candidate = ArtifactReference("candidate", "cif", "runs/a.cif", "workflow")
    repair = RepairRecommendation(RepairType.RETRY_RETRIEVAL, "transient failure", {"retry": 1}, False, "result")
    record = EvaluationRecord(candidate, "workflow", (EvaluationCriterionResult("valid", None),), EvaluationStatus.INCONCLUSIVE, repair)
    assert EvaluationRecord.from_dict(record.to_dict()) == record
    with pytest.raises(ValueError):
        RepairRecommendation("EDIT_SOURCE", "bad", {}, False, "result")  # type: ignore[arg-type]


def test_artifact_paths_are_relative_and_hashes_validated() -> None:
    for path in ("../secret", "/etc/passwd", r"C:\repository\src\x.py", r"\\server\share\x"):
        with pytest.raises(ValueError):
            ArtifactReference("a", "result", path, "run")
    with pytest.raises(ValueError, match="sha256"):
        ArtifactReference("a", "result", "result.json", "run", "abc")


def test_write_scope_rejects_cross_platform_escape(tmp_path) -> None:
    scope = WriteScope(str(tmp_path / "agent-run"))
    assert scope.resolve("artifacts/result.json") == (tmp_path / "agent-run" / "artifacts" / "result.json").resolve()
    for path in ("../outside", r"..\outside", "/etc/passwd", r"C:\repository\src\x.py"):
        with pytest.raises(ValueError):
            scope.resolve(path)


def test_identifier_factory_is_deterministic_when_injected() -> None:
    from uuid import UUID

    fixed = UUID("00000000-0000-0000-0000-000000000001")
    assert new_identifier("step", lambda: fixed) == "step_00000000000000000000000000000001"


def test_utc_clock_rejects_naive_datetime() -> None:
    from datetime import datetime

    with pytest.raises(ValueError, match="timezone-aware"):
        utc_now_iso(lambda: datetime(2026, 1, 1))


def test_plan_step_and_tool_call_transitions() -> None:
    step = PlanStep("s", "inspect_run", "inspect", {})
    step = transition_plan_step(step, PlanStepStatus.READY)
    step = transition_plan_step(step, PlanStepStatus.RUNNING)
    step = transition_plan_step(step, PlanStepStatus.SUCCEEDED)
    with pytest.raises(ValueError, match="illegal"):
        transition_plan_step(step, PlanStepStatus.RUNNING)

    call = ToolCall("c", "inspect_run", {}, ActorRole.ORCHESTRATOR)
    call = transition_tool_call(call, ToolCallStatus.RUNNING)
    call = transition_tool_call(call, ToolCallStatus.SUCCEEDED)
    with pytest.raises(ValueError, match="illegal"):
        transition_tool_call(call, ToolCallStatus.RUNNING)


def test_state_invariants_for_candidate_result_budget_and_approval() -> None:
    candidate = ArtifactReference("candidate", "candidate", "candidate.cif", "run")
    result = ArtifactReference("result", "workflow_result", "result.json", "run")
    run = WorkflowRunReference("run", "OPTIMAL", result, candidate)
    with pytest.raises(ValueError, match="budget usage"):
        _minimal_state(workflow_runs=(run,), current_candidate=candidate)
    with pytest.raises(ValueError, match="artifact produced"):
        _minimal_state(current_candidate=candidate)

    budgets = AgentBudgets().consume(BudgetResource.WORKFLOW_RUNS)
    state = _minimal_state(workflow_runs=(run,), current_candidate=candidate, budgets=budgets)
    assert state.current_candidate == candidate


def test_appending_workflow_run_consumes_budget_atomically() -> None:
    result = ArtifactReference("result", "workflow_result", "result.json", "run")
    state = _minimal_state().append_workflow_run(WorkflowRunReference("run", "INFEASIBLE", result))
    assert state.budgets.usage.workflow_runs_used == 1
    assert len(state.workflow_runs) == 1


def test_decision_result_must_reference_known_tool_call() -> None:
    decision = DecisionRecord("d", ActorRole.PLANNER, "select", "selected supported tool", (), "2026-01-01T00:00:00Z", result_ref="missing")
    with pytest.raises(ValueError, match="known tool call"):
        _minimal_state(decisions=(decision,))


def test_tool_result_and_approved_request_references_must_be_known() -> None:
    call = ToolCall("call", "run_csp", {}, ActorRole.ORCHESTRATOR, result_ref="missing")
    with pytest.raises(ValueError, match="known result artifact"):
        _minimal_state(tool_calls=(call,))
    approval = ApprovalRequest(
        "approval", ApprovalCategory.EXPAND_SEARCH_SPACE, "expand", {"new": 2}, ActorRole.PLANNER,
        "missing", "2026-01-01T00:00:00Z", status="APPROVED",
        decided_at="2026-01-01T00:01:00Z", decided_by=ActorRole.USER,
    )
    with pytest.raises(ValueError, match="existing plan step"):
        _minimal_state(approvals=(approval,))


def test_terminal_state_rejects_pending_execution_and_new_transitions() -> None:
    running_step = replace(_minimal_state().plan.steps[0], status=PlanStepStatus.RUNNING)
    plan = AgentPlan("plan_1", "find a candidate", (running_step,))
    with pytest.raises(ValueError, match="pending planned execution"):
        _minimal_state(plan=plan, status=AgentRunStatus.BLOCKED)
    terminal_step = replace(running_step, status=PlanStepStatus.FAILED)
    terminal = _minimal_state(plan=AgentPlan("plan_1", "find a candidate", (terminal_step,)), status=AgentRunStatus.BLOCKED)
    with pytest.raises(ValueError, match="terminal"):
        terminal.append_tool_call(ToolCall("c", "inspect_run", {}, ActorRole.ORCHESTRATOR))


def test_pending_run_transitions_to_running() -> None:
    assert _minimal_state().transition_status(AgentRunStatus.RUNNING).status is AgentRunStatus.RUNNING
    with pytest.raises(ValueError, match="illegal"):
        _minimal_state().transition_status(AgentRunStatus.SUCCESS)


def test_success_requires_plan_approval_and_approved_reference() -> None:
    step = PlanStep("step_1", "inspect_run", "inspect", {}, approval_category=ApprovalCategory.EXPAND_SEARCH_SPACE,
                    status=PlanStepStatus.SUCCEEDED)
    plan = AgentPlan("plan_1", "find a candidate", (step,), required_approvals=(ApprovalCategory.EXPAND_SEARCH_SPACE,))
    with pytest.raises(ValueError, match="every required approval"):
        _minimal_state(plan=plan, status=AgentRunStatus.SUCCESS)
    approval = ApprovalRequest(
        "approval_1", ApprovalCategory.EXPAND_SEARCH_SPACE, "expand", {"new": 2}, ActorRole.PLANNER,
        "step_1", "2026-01-01T00:00:00Z", status="APPROVED",
        decided_at="2026-01-01T00:01:00Z", decided_by=ActorRole.USER,
    )
    assert _minimal_state(plan=plan, approvals=(approval,), status=AgentRunStatus.SUCCESS).status is AgentRunStatus.SUCCESS
