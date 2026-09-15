from __future__ import annotations

from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


class _InvalidLLM:
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        _ = messages, tools
        return {"choices": [{"message": {"content": "{\"action_id\":\"totally_invalid\",\"rationale\":\"test\"}"}}]}


def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
    return {
        "feasible": True,
        "primary_objective": 0.2,
        "property_estimate": 0.2,
        "valid_for_learning": True,
        "solver_calls": 2,
        "retrieval_calls": 2,
        "run_reference": {"action": compiled["action_id"]},
    }


def test_invalid_action_fallback_e2e(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 2
    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        llm_client=_InvalidLLM(),  # type: ignore[arg-type]
        executor=_executor,
    )
    result = engine.start(query="TiO2 optimize high property x", auto_run=True)
    session = engine.get(result.session_id)
    assert session.iteration_history
    assert any(
        bool(item.get("arbitration", {}).get("gate", {}).get("via_fallback"))
        or str(item.get("arbitration", {}).get("llm_proposal", {}).get("source", "")).startswith("fallback")
        for item in session.iteration_history
    )
