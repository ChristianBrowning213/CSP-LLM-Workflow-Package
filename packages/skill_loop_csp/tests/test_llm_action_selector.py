from __future__ import annotations

from typing import Any

from sok_llm_orchestrator.optimization.llm_action_selector import propose_action


class _FakeClient:
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        _ = messages, tools
        return {
            "choices": [
                {
                    "message": {
                        "content": "{\"action_id\":\"guided_hybrid_balanced\",\"rationale\":\"best expected reward\"}"
                    }
                }
            ]
        }


def test_llm_action_selector_parses_json_response() -> None:
    proposal = propose_action(
        llm_client=_FakeClient(),  # type: ignore[arg-type]
        candidate_action_ids=["baseline_control", "guided_hybrid_balanced"],
        registry_summary_payload=[],
        session_context={},
    )
    assert proposal.action_id == "guided_hybrid_balanced"

