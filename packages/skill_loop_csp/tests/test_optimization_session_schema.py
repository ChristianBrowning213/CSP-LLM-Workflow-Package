from __future__ import annotations

from sok_llm_orchestrator.optimization.session_schema import (
    OptimizationSession,
    stable_session_id,
    validate_optimization_session,
)


def test_optimization_session_schema_roundtrip() -> None:
    sid = stable_session_id({"query_text": "TiO2 optimize"}, "stub", {"max_iterations": 2})
    session = OptimizationSession(
        session_id=sid,
        status="READY",
        task_spec={"query_text": "TiO2 optimize"},
        clarification_state={"ready": True, "pending_questions": []},
        optimization_plan={"schema_version": "optimization.plan.v1"},
        budget_state={"config": {"max_iterations": 2}},
    )
    payload = session.to_dict()
    validate_optimization_session(payload)
    loaded = OptimizationSession.from_dict(payload)
    assert loaded.session_id == sid
    assert loaded.status == "READY"

