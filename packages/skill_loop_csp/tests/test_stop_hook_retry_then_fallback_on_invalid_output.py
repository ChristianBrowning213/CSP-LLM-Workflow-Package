from __future__ import annotations

from typing import Any

from sok_llm_orchestrator.optimization.stop_hook import evaluate_stop_hook


class _AlwaysInvalidStopHookClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        _ = messages, tools
        self.calls += 1
        return {"choices": [{"message": {"content": "not-json-at-all"}}]}


def test_stop_hook_retry_then_fallback_on_invalid_output() -> None:
    client = _AlwaysInvalidStopHookClient()
    decision = evaluate_stop_hook(
        llm_client=client,  # type: ignore[arg-type]
        context={
            "infeasible_streak": 4,
            "recovery_stage": 2,
            "recovery_regime": "broadened_retrieval_and_templates",
            "recovery_attempt_count": 5,
            "recovery_exhausted": False,
            "remaining_iterations": 2,
            "hard_constraint_boundary_reached": False,
            "task_meaning_ambiguity": False,
            "stuck_reason": "repeated_infeasibility",
        },
        allow_user_clarification=True,
    )
    assert client.calls == 2
    assert decision.source == "fallback_after_invalid_output"
    telemetry = decision.telemetry or {}
    assert int(telemetry.get("retry_count", 0)) == 1
    assert int(telemetry.get("fallback_count", 0)) == 1
