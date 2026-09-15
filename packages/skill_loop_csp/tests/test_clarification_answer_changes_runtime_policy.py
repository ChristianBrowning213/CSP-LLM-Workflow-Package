from __future__ import annotations

from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


def _simple_executor(_: Path):  # type: ignore[no-untyped-def]
    def _run(__: str, compiled: dict[str, Any]) -> dict[str, Any]:
        return {
            "feasible": True,
            "primary_objective": 0.1,
            "property_estimate": 0.1,
            "valid_for_learning": True,
            "solver_calls": 1,
            "retrieval_calls": 1,
            "run_reference": {"action": str(compiled.get("action_id", ""))},
        }

    return _run


def test_clarification_answer_changes_runtime_policy(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 1
    settings.optimization_allow_midloop_clarification = True
    settings.optimization_exploration_rate = 0.0
    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        executor=_simple_executor(workdir),
    )
    start = engine.start(query="TiO2 optimize property x", auto_run=False)
    cont = engine.continue_session(
        session_id=start.session_id,
        clarification_answer="Keep rutile strict symmetry; do not relax symmetry.",
        max_new_iterations=1,
    )
    session = engine.get(cont.session_id)
    policy = session.policy_state.get("clarification_policy", {})
    assert isinstance(policy, dict)
    assert policy.get("preserve_strict_symmetry") is True
    assert policy.get("allow_symmetry_relaxation") is False
    assert session.clarification_state.get("answer_applied") is True
    assert session.clarification_state.get("answer_policy_effects", {}).get("preserve_strict_symmetry") is True
