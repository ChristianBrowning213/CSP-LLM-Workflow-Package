from __future__ import annotations

import pytest

from llm_csp.agentic.approvals import ApprovalRequest, action_requires_approval, has_required_approval, transition_approval
from llm_csp.agentic.budgets import AgentBudgets, BudgetExceededError, BudgetLimits, BudgetResource
from llm_csp.agentic.models import ActorRole, ApprovalCategory, ApprovalStatus, AutomaticAction


def _approval() -> ApprovalRequest:
    return ApprovalRequest(
        "approval_1", ApprovalCategory.EXPAND_SEARCH_SPACE, "expand one bound", {"old": 4, "new": 6},
        ActorRole.PLANNER, "step_1", "2026-01-01T00:00:00Z",
    )


def test_budget_defaults_match_architecture() -> None:
    limits = AgentBudgets().limits
    assert limits == BudgetLimits(2, 1, 1, 2, 3600)


def test_budget_consumption_is_immutable_and_cannot_exceed_limit() -> None:
    original = AgentBudgets()
    first = original.consume(BudgetResource.WORKFLOW_RUNS)
    second = first.consume(BudgetResource.WORKFLOW_RUNS)
    assert original.usage.workflow_runs_used == 0
    assert second.remaining(BudgetResource.WORKFLOW_RUNS) == 0
    assert second.exhausted(BudgetResource.WORKFLOW_RUNS)
    assert not second.can_consume(BudgetResource.WORKFLOW_RUNS)
    with pytest.raises(BudgetExceededError):
        second.consume(BudgetResource.WORKFLOW_RUNS)


def test_budget_serialization_is_strict() -> None:
    assert AgentBudgets.from_dict(AgentBudgets().to_dict()) == AgentBudgets()
    with pytest.raises(TypeError, match="unexpected"):
        BudgetLimits.from_dict({"unknown": 1})


@pytest.mark.parametrize("target", [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED])
def test_human_approval_transitions(target) -> None:
    result = transition_approval(_approval(), target, decided_by=ActorRole.USER, decided_at="2026-01-01T00:01:00Z")
    assert result.status is target
    assert has_required_approval(
        ApprovalCategory.EXPAND_SEARCH_SPACE, [result], request_ref="step_1", proposed_change={"old": 4, "new": 6}
    ) is (target is ApprovalStatus.APPROVED)
    with pytest.raises(ValueError, match="illegal"):
        transition_approval(result, ApprovalStatus.PENDING, decided_by=ActorRole.USER, decided_at="2026-01-01T00:02:00Z")


def test_agent_cannot_approve_its_own_request() -> None:
    with pytest.raises(ValueError, match="only USER"):
        transition_approval(_approval(), ApprovalStatus.APPROVED, decided_by=ActorRole.ORCHESTRATOR, decided_at="2026-01-01T00:01:00Z")
    payload = _approval().to_dict() | {
        "status": "APPROVED", "decided_by": "PLANNER", "decided_at": "2026-01-01T00:01:00Z"
    }
    with pytest.raises(ValueError, match="only USER"):
        ApprovalRequest.from_dict(payload)


def test_approval_gate_is_category_and_request_specific() -> None:
    approved = transition_approval(_approval(), ApprovalStatus.APPROVED, decided_by=ActorRole.USER, decided_at="2026-01-01T00:01:00Z")
    assert action_requires_approval(ApprovalCategory.EXPAND_SEARCH_SPACE)
    assert not action_requires_approval(None)
    assert not has_required_approval(
        ApprovalCategory.EXPAND_SEARCH_SPACE, [approved], request_ref="other", proposed_change={"old": 4, "new": 6}
    )
    assert not has_required_approval(
        ApprovalCategory.EXPAND_SEARCH_SPACE, [approved], request_ref="step_1", proposed_change={"old": 4, "new": 7}
    )


def test_automatic_action_set_is_closed_and_narrow() -> None:
    assert {item.value for item in AutomaticAction} == {
        "RETRY_MODEL_FORMAT", "READ_EXISTING_RUN", "RETRY_RETRIEVAL", "EXECUTE_APPROVED_STEP"
    }
    with pytest.raises(ValueError):
        AutomaticAction("EDIT_SOURCE")
