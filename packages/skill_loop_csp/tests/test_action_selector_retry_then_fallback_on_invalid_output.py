from __future__ import annotations

from typing import Any

from sok_llm_orchestrator.optimization.llm_action_selector import propose_action


class _AlwaysInvalidSelectorClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        _ = messages, tools
        self.calls += 1
        return {"choices": [{"message": {"content": "```bad```"}}]}


def test_action_selector_retry_then_fallback_on_invalid_output() -> None:
    client = _AlwaysInvalidSelectorClient()
    proposal = propose_action(
        llm_client=client,  # type: ignore[arg-type]
        candidate_action_ids=["guided_hybrid_balanced", "baseline_control"],
        registry_summary_payload=[],
        session_context={},
    )
    assert client.calls == 2
    assert proposal.source == "fallback_after_invalid_output"
    telemetry = proposal.telemetry
    assert int(telemetry.get("retry_count", 0)) == 1
    assert int(telemetry.get("fallback_count", 0)) == 1
