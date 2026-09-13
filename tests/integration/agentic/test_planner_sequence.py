from datetime import datetime, timezone

from llm_csp.agentic import AgentPlan, AgentRunState, Planner
from llm_csp.agentic.contracts import validate_tool_input
from llm_csp.agentic.model import FakeAgentModel
from llm_csp.agentic.model.fixtures import normal_csp_plan
from llm_csp.agentic.models import ParsedIntent
from llm_csp.agentic.planner import PlannerStatus, apply_planner_result


def test_fake_model_to_validated_initial_plan_without_tool_execution() -> None:
    goal = "Generate a candidate for SrTiO3"
    state = AgentRunState("agent", goal, ParsedIntent(goal, "SrTiO3"), AgentPlan("empty", goal, ()))
    planner = Planner(
        id_factory=lambda prefix: f"{prefix}_fixture",
        clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    result = planner.plan(state=state, model=FakeAgentModel(normal_csp_plan()))
    assert result.status is PlannerStatus.PLANNED
    assert all(validate_tool_input(step.tool_name, step.inputs) for step in result.plan.steps)
    updated = apply_planner_result(
        state, result,
        id_factory=lambda prefix: f"{prefix}_fixture",
        clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert updated.plan == result.plan
    assert updated.workflow_runs == ()
    assert updated.tool_calls == ()
