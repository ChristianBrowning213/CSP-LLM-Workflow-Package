from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


class _IntermittentInvalidLLM:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        _ = tools
        self.calls += 1
        if self.calls % 2 == 1:
            content = "{\"action_id\":\"not_registered_action\",\"rationale\":\"invalid on purpose\"}"
            return {"choices": [{"message": {"content": content}}]}
        prompt = json.loads(str(messages[-1]["content"]))
        candidates = list(prompt.get("candidate_action_ids", []))
        chosen = candidates[0] if candidates else "baseline_control"
        content = json.dumps({"action_id": chosen, "rationale": "valid proposal"})
        return {"choices": [{"message": {"content": content}}]}


def _executor(_: str, compiled: dict[str, Any]) -> dict[str, Any]:
    action = str(compiled["action_id"])
    objective = 0.2
    if action == "guided_hybrid_balanced":
        objective = 0.7
    return {
        "feasible": True,
        "primary_objective": objective,
        "property_estimate": objective,
        "valid_for_learning": True,
        "solver_calls": 2,
        "retrieval_calls": 2,
        "run_reference": {"action": action},
    }


def test_invalid_actions_recover_multi_iteration(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 6
    settings.optimization_exploration_rate = 0.5
    settings.optimization_allow_midloop_clarification = False
    settings.optimization_stagnation_window = 12
    llm = _IntermittentInvalidLLM()
    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="stub",
        llm_client=llm,  # type: ignore[arg-type]
        executor=_executor,
    )
    start = engine.start(query="TiO2 optimize high property x", auto_run=True)
    session = engine.get(start.session_id)
    assert len(session.iteration_history) >= 4
    fallback_count = sum(
        1 for item in session.iteration_history if bool(item["arbitration"]["gate"]["via_fallback"])
    )
    controller_fallback_count = sum(
        1
        for item in session.iteration_history
        if str(item.get("arbitration", {}).get("llm_proposal", {}).get("source", "")).startswith("fallback")
    )
    accepted_count = sum(
        1 for item in session.iteration_history if bool(item["arbitration"]["gate"]["accepted"])
    )
    assert (fallback_count + controller_fallback_count) >= 2
    assert accepted_count >= 1
    assert session.status in {"STOPPED", "COMPLETED", "READY"}
    assert all("arbitration" in item and "gate" in item["arbitration"] for item in session.iteration_history)
