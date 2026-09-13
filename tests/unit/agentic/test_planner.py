from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from llm_csp.agentic import Planner
from llm_csp.agentic.budgets import AgentBudgets, BudgetLimits, BudgetResource
from llm_csp.agentic.contracts import TOOL_CONTRACTS, validate_tool_input
from llm_csp.agentic.model import AgentModelError, FakeAgentModel, ModelErrorCode
from llm_csp.agentic.model.fixtures import (
    cyclic_plan,
    normal_csp_plan,
    retrieval_only_plan,
    unknown_tool_plan,
    user_input_required,
)
from llm_csp.agentic.models import (
    AgentPlan,
    ConstraintKind,
    ConstraintRecord,
    ParsedIntent,
    _jsonable,
)
from llm_csp.agentic.planner import PlannerStatus, apply_planner_result, planner_tool_summaries
from llm_csp.agentic.state import AgentRunState
from llm_csp.agentic.termination import AgentRunStatus


class IDs:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, prefix: str) -> str:
        self.count += 1
        return f"{prefix}_{self.count}"


CLOCK = lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)


def state(*, goal: str = "Generate a candidate for SrTiO3", constraints=(), formula="SrTiO3", budgets=None):
    return AgentRunState(
        "agent_1",
        goal,
        ParsedIntent(goal, formula, constraints=tuple(constraints)),
        AgentPlan("unplanned", goal, ()),
        budgets=budgets or AgentBudgets(),
    )


def planner() -> Planner:
    return Planner(id_factory=IDs(), clock=CLOCK)


def with_context(payload, records):
    value = dict(payload)
    value["hard_constraints"] = [x.to_dict() for x in records if x.kind is ConstraintKind.HARD_CONSTRAINT]
    value["soft_preferences"] = [x.to_dict() for x in records if x.kind is ConstraintKind.SOFT_PREFERENCE]
    value["success_criteria"] = [x.to_dict() for x in records if x.kind is ConstraintKind.SUCCESS_CRITERION]
    return value


def test_valid_normal_plan_is_typed_and_does_not_duplicate_retrieval() -> None:
    result = planner().plan(state=state(), model=FakeAgentModel(normal_csp_plan()))
    assert result.status is PlannerStatus.PLANNED
    assert result.plan is not None
    assert [step.tool_name.value for step in result.plan.steps] == ["run_csp"]
    assert result.plan.steps[0].step_id.startswith("step_")
    assert result.provenance.output_plan_id == result.plan.plan_id
    assert result.format_attempts[0].error_code is None


def test_retrieval_only_plan_and_registry_exposure_come_from_contracts() -> None:
    goal = "Find crystal evidence for SrTiO3"
    result = planner().plan(state=state(goal=goal), model=FakeAgentModel(retrieval_only_plan()))
    assert result.status is PlannerStatus.PLANNED
    assert result.plan.steps[0].tool_name.value == "search_crystal_db"
    summaries = planner_tool_summaries()
    assert [x["name"] for x in summaries] == [x.value for x in TOOL_CONTRACTS]
    assert all("input_fields" in x and "description" in x for x in summaries)


@pytest.mark.parametrize("bad", [unknown_tool_plan(), cyclic_plan()])
def test_unknown_tools_and_cycles_are_rejected_without_fallback(bad) -> None:
    if bad["goal"].startswith("Find crystal"):
        original = state(goal=bad["goal"])
    else:
        original = state()
    result = planner().plan(state=original, model=FakeAgentModel([bad, bad, bad]))
    assert result.status is PlannerStatus.INVALID_MODEL_OUTPUT
    assert result.plan is None
    assert len(result.format_attempts) == 3


def test_argument_schema_rejects_arbitrary_paths_before_execution() -> None:
    bad = normal_csp_plan()
    bad["steps"][0]["inputs"]["output_root"] = "../../outside"
    result = planner().plan(state=state(), model=FakeAgentModel([bad, bad, bad]))
    assert result.status is PlannerStatus.INVALID_MODEL_OUTPUT
    assert "unexpected field" in str(result.error)


def test_hard_soft_and_success_records_are_preserved_without_reclassification() -> None:
    records = (
        ConstraintRecord(ConstraintKind.HARD_CONSTRAINT, "cubic family", "topology_family", "cubic"),
        ConstraintRecord(ConstraintKind.SOFT_PREFERENCE, "prefer small cell", "small_cell", True),
        ConstraintRecord(ConstraintKind.SUCCESS_CRITERION, "candidate generated", "candidate_generated", True),
    )
    request = normal_csp_plan()
    request["steps"][0]["inputs"]["request"]["constraints"] = [{"topology_family": "cubic"}]
    request = with_context(request, records)
    result = planner().plan(state=state(constraints=records), model=FakeAgentModel(request))
    assert result.status is PlannerStatus.PLANNED
    assert result.preserved_constraints == records

    dropped = with_context(normal_csp_plan(), records)
    dropped["hard_constraints"] = []
    rejected = planner().plan(state=state(constraints=records), model=FakeAgentModel([dropped] * 3))
    assert rejected.status is PlannerStatus.INVALID_MODEL_OUTPUT
    assert "preserve" in str(rejected.error)


def test_run_formula_must_preserve_parsed_target() -> None:
    bad = normal_csp_plan(formula="NaCl")
    bad["goal"] = "Generate a candidate for SrTiO3"
    result = planner().plan(state=state(), model=FakeAgentModel([bad] * 3))
    assert result.status is PlannerStatus.INVALID_MODEL_OUTPUT
    assert "target_formula" in str(result.error)


def test_schema_retry_consumes_only_format_budget_and_sends_correction() -> None:
    model = FakeAgentModel(["malformed", normal_csp_plan()])
    result = planner().plan(state=state(), model=model)
    assert result.status is PlannerStatus.PLANNED
    assert result.budgets.usage.model_format_retries_used == 1
    assert result.budgets.usage.workflow_runs_used == 0
    assert result.budgets.usage.repair_attempts_used == 0
    assert len(result.format_attempts) == 2
    assert model.calls[1]["input_payload"]["format_correction"]["error_code"] == "MODEL_OUTPUT_INVALID"


def test_format_retry_never_exceeds_remaining_budget() -> None:
    budgets = AgentBudgets(BudgetLimits(max_model_format_retries=1))
    model = FakeAgentModel(["bad", "bad", normal_csp_plan()])
    result = planner().plan(state=state(budgets=budgets), model=model)
    assert result.status is PlannerStatus.INVALID_MODEL_OUTPUT
    assert result.error.code is ModelErrorCode.MODEL_FORMAT_RETRY_EXHAUSTED
    assert len(model.calls) == 2
    assert result.budgets.remaining(BudgetResource.MODEL_FORMAT_RETRIES) == 0


def test_model_unavailable_is_not_retried_or_applied() -> None:
    original = state()
    model = FakeAgentModel(AgentModelError(ModelErrorCode.MODEL_UNAVAILABLE, "offline"))
    result = planner().plan(state=original, model=model)
    assert result.status is PlannerStatus.MODEL_UNAVAILABLE
    assert len(model.calls) == 1
    assert result.budgets == original.budgets
    with pytest.raises(ValueError):
        apply_planner_result(original, result)


def test_structured_clarification_and_missing_formula_do_not_create_plan() -> None:
    explicit = planner().plan(
        state=state(goal="Generate a candidate", formula=None),
        model=FakeAgentModel(user_input_required()),
    )
    assert explicit.status is PlannerStatus.USER_INPUT_REQUIRED
    assert explicit.clarification.missing_field == "target_formula"

    proposed = normal_csp_plan()
    proposed["goal"] = "Generate a candidate"
    inferred = planner().plan(
        state=state(goal="Generate a candidate", formula=None), model=FakeAgentModel(proposed)
    )
    assert inferred.status is PlannerStatus.USER_INPUT_REQUIRED
    assert inferred.plan is None


def test_apply_success_records_audit_without_executing_or_marking_success() -> None:
    original = state()
    result = planner().plan(state=original, model=FakeAgentModel(normal_csp_plan()))
    updated = apply_planner_result(original, result, id_factory=IDs(), clock=CLOCK)
    assert updated.plan == result.plan
    assert updated.status is AgentRunStatus.PENDING
    assert updated.workflow_runs == () and updated.tool_calls == () and updated.current_candidate is None
    assert updated.decisions[-1].actor.value == "PLANNER"
    assert "validated plan" in updated.decisions[-1].rationale_summary


def test_apply_clarification_sets_pending_user_action() -> None:
    original = state(goal="Generate a candidate", formula=None)
    result = planner().plan(state=original, model=FakeAgentModel(user_input_required()))
    updated = apply_planner_result(original, result)
    assert updated.status is AgentRunStatus.USER_INPUT_REQUIRED
    assert updated.pending_user_action == result.clarification.question
    assert updated.plan == original.plan


def test_approval_sensitive_step_is_marked_but_no_approval_is_created() -> None:
    records = (ConstraintRecord(ConstraintKind.HARD_CONSTRAINT, "larger design", "expanded", True),)
    payload = normal_csp_plan()
    payload["steps"][0]["approval_category"] = "EXPAND_SEARCH_SPACE"
    payload["steps"][0]["inputs"]["request"]["constraints"] = [{"expanded": True}]
    payload = with_context(payload, records)
    result = planner().plan(state=state(constraints=records), model=FakeAgentModel(payload))
    assert result.status is PlannerStatus.PLANNED
    assert result.plan.steps[0].status.value == "AWAITING_APPROVAL"
    assert result.plan.required_approvals[0].value == "EXPAND_SEARCH_SPACE"
    updated = apply_planner_result(state(constraints=records), result, id_factory=IDs(), clock=CLOCK)
    assert updated.approvals == ()


def test_planner_output_validates_against_ticket20_contract_without_execution() -> None:
    original = state()
    result = planner().plan(state=original, model=FakeAgentModel(normal_csp_plan()))
    for step in result.plan.steps:
        assert validate_tool_input(step.tool_name, step.inputs).to_dict() == _jsonable(step.inputs)
    assert original.workflow_runs == () and original.tool_calls == ()


def test_planning_has_no_tool_or_filesystem_side_effects(tmp_path, monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("scientific execution must not be called by Planner")

    monkeypatch.setattr("llm_csp.agentic.tools.execute_tool", forbidden)
    before = tuple(tmp_path.iterdir())
    result = planner().plan(state=state(), model=FakeAgentModel(normal_csp_plan()))
    after = tuple(tmp_path.iterdir())
    assert result.status is PlannerStatus.PLANNED
    assert before == after == ()
