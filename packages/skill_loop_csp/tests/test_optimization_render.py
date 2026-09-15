from __future__ import annotations

from sok_llm_orchestrator.optimization.render import render_session_summary
from sok_llm_orchestrator.optimization.session_schema import OptimizationSession


def test_render_session_summary_contains_key_fields() -> None:
    session = OptimizationSession(
        session_id="s1",
        status="READY",
        task_spec={"query_text": "TiO2"},
        clarification_state={"ready": True},
        optimization_plan={"schema_version": "optimization.plan.v1"},
        budget_state={"config": {"max_iterations": 3}},
    )
    text = render_session_summary(session)
    assert "Session: s1" in text
    assert "Status: READY" in text

