from __future__ import annotations

from typing import Any

from sok_llm_orchestrator.optimization.llm_action_selector import propose_action


class _RepeatedJsonClient:
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        _ = messages, tools
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"action_id":"guided_hybrid_balanced","ranked_action_ids":["guided_hybrid_balanced"],"rationale":"x"}'
                            '{"action_id":"baseline_control","ranked_action_ids":["baseline_control"],"rationale":"y"}'
                        )
                    }
                }
            ]
        }


def test_action_selector_rejects_repeated_json_payloads() -> None:
    proposal = propose_action(
        llm_client=_RepeatedJsonClient(),  # type: ignore[arg-type]
        candidate_action_ids=["guided_hybrid_balanced", "baseline_control"],
        registry_summary_payload=[],
        session_context={},
    )
    assert proposal.source == "fallback_after_invalid_output"
    telemetry = proposal.telemetry
    assert int(telemetry.get("parse_failures", 0)) >= 1
    assert telemetry.get("failure_reason") == "repeated_json_payload"
