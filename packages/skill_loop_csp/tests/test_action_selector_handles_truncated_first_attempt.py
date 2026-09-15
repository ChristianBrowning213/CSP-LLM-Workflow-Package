from __future__ import annotations

from typing import Any

from sok_llm_orchestrator.optimization.llm_action_selector import propose_action


class _TokenSensitiveSelectorClient:
    def __init__(self) -> None:
        self.calls: list[int | None] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        _ = messages, tools, temperature
        self.calls.append(max_tokens)
        if not isinstance(max_tokens, int) or max_tokens < 160:
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"action_id":"guided_property_push","ranked_action_ids":'
                                '["guided_property_push","cell_policy_probe"],"rationale":"truncated'
                            )
                        }
                    }
                ]
            }
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"action_id":"guided_property_push",'
                            '"ranked_action_ids":["guided_property_push","cell_policy_probe"],'
                            '"rationale":"highest property signal"}'
                        )
                    }
                }
            ]
        }


def test_action_selector_handles_truncated_first_attempt_when_token_cap_allows_completion() -> None:
    client = _TokenSensitiveSelectorClient()
    proposal = propose_action(
        llm_client=client,  # type: ignore[arg-type]
        candidate_action_ids=["guided_property_push", "cell_policy_probe"],
        registry_summary_payload=[],
        session_context={},
    )
    assert proposal.source == "llm"
    assert proposal.action_id == "guided_property_push"
    assert proposal.ranked_action_ids == ["guided_property_push", "cell_policy_probe"]
    assert proposal.telemetry.get("fallback_count") == 0
    assert client.calls == [180]
