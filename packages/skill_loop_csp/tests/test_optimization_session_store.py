from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.optimization.session_schema import OptimizationSession
from sok_llm_orchestrator.optimization.session_store import OptimizationSessionStore


def test_session_store_save_and_load(workdir: Path) -> None:
    store = OptimizationSessionStore(workdir)
    session = OptimizationSession(
        session_id="sid-1",
        status="READY",
        task_spec={"query_text": "TiO2"},
        clarification_state={"ready": True, "pending_questions": []},
        optimization_plan={"schema_version": "optimization.plan.v1"},
        budget_state={"config": {"max_iterations": 3}},
        iteration_history=[{"iteration_index": 0, "score": 0.1}],
    )
    path = store.save(session)
    assert path.exists()
    assert (workdir / "optimization" / "sessions" / "sid-1" / "iterations" / "000.json").exists()
    loaded = store.load("sid-1")
    assert loaded.iteration_history[0]["score"] == 0.1

