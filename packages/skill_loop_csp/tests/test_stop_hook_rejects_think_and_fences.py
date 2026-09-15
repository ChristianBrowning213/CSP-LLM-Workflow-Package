from __future__ import annotations

from typing import Any

from sok_llm_orchestrator.optimization.stop_hook import evaluate_stop_hook


class _ThinkFenceClient:
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        _ = messages, tools
        return {
            "choices": [
                {
                    "message": {
                        "content": "<think>long reasoning</think>\n```json\n{\"decision\":\"continue_autonomously\"}\n```"
                    }
                }
            ]
        }


def test_stop_hook_rejects_think_and_fences() -> None:
    decision = evaluate_stop_hook(
        llm_client=_ThinkFenceClient(),  # type: ignore[arg-type]
        context={
            "infeasible_streak": 3,
            "recovery_stage": 2,
            "recovery_regime": "broadened_retrieval_and_templates",
            "recovery_attempt_count": 4,
            "recovery_exhausted": False,
            "remaining_iterations": 2,
            "hard_constraint_boundary_reached": False,
            "task_meaning_ambiguity": False,
            "stuck_reason": "repeated_infeasibility",
        },
        allow_user_clarification=True,
    )
    assert decision.source == "fallback_after_invalid_output"
    telemetry = decision.telemetry or {}
    assert int(telemetry.get("parse_failures", 0)) >= 1
    assert int(telemetry.get("contains_think_count", 0)) >= 1
    assert int(telemetry.get("contains_fence_count", 0)) >= 1
