from __future__ import annotations

from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.loop import OptimizationEngine


class _VerboseModelClient:
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        _ = messages, tools
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            "<think>I should reason for a long time.</think>\n"
                            "```json\n{\"decision\":\"continue_autonomously\"}\n```\n"
                            "{\"decision\":\"continue_autonomously\"}"
                        )
                    }
                }
            ]
        }


def _always_infeasible(_: Path):  # type: ignore[no-untyped-def]
    def _run(__: str, compiled: dict[str, Any]) -> dict[str, Any]:
        return {
            "feasible": False,
            "primary_objective": None,
            "property_estimate": None,
            "valid_for_learning": False,
            "solver_calls": 1,
            "retrieval_calls": 1,
            "run_reference": {"action": str(compiled.get("action_id", ""))},
        }

    return _run


def test_controller_calls_do_not_block_on_verbose_model_stub(workdir: Path) -> None:
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.optimization_max_iterations = 4
    settings.optimization_stagnation_window = 1
    settings.optimization_max_failed_iterations = 1
    settings.optimization_allow_midloop_clarification = True
    settings.optimization_exploration_rate = 0.0
    engine = OptimizationEngine(
        workspace=workdir,
        settings=settings,
        mode="live",
        llm_client=_VerboseModelClient(),  # type: ignore[arg-type]
        executor=_always_infeasible(workdir),
    )
    result = engine.start(query="TiO2 optimize property x", auto_run=True)
    session = engine.get(result.session_id)
    assert len(session.iteration_history) >= 2
    assert session.status in {"WAITING_CLARIFICATION", "STOPPED"}
    stats = session.policy_state.get("controller_output_stats", {})
    assert isinstance(stats, dict)
    selector = stats.get("action_selector", {})
    stop_hook = stats.get("stop_hook", {})
    assert isinstance(selector, dict)
    assert isinstance(stop_hook, dict)
    assert int(selector.get("fallback_count", 0)) >= 1
    assert int(selector.get("parse_failures", 0)) >= 1
    assert int(stop_hook.get("fallback_count", 0)) >= 1
    assert int(stop_hook.get("parse_failures", 0)) >= 1
