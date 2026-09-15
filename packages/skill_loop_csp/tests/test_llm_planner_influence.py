from __future__ import annotations

from typing import Any

from sok_llm_orchestrator.optimization.planner import build_optimization_plan


class _PlannerLLM:
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        _ = messages, tools
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"action_family_priorities":["retrieval_explore","guided_exploit","baseline_control"],'
                            '"initial_hypotheses":["Text/fingerprint exploration should diversify priors before exploitation."],'
                            '"exploration_rate":0.55,"rationale":"avoid early lock-in"}'
                        )
                    }
                }
            ]
        }


def test_llm_planner_influences_priorities_and_exploration() -> None:
    task = {
        "composition_target": "TiO2",
        "property_bias": "property_x",
        "symmetry_request": {"space_group": "P42/mnm", "hardness": "soft"},
    }
    baseline = build_optimization_plan(
        task_spec=task,
        max_iterations=4,
        exploration_rate=0.2,
        stagnation_window=3,
    )
    influenced = build_optimization_plan(
        task_spec=task,
        max_iterations=4,
        exploration_rate=0.2,
        stagnation_window=3,
        llm_client=_PlannerLLM(),  # type: ignore[arg-type]
    )
    base_payload = baseline.to_dict()
    llm_payload = influenced.to_dict()
    assert llm_payload["schema_version"] == "optimization.plan.v1"
    assert llm_payload["action_family_priorities"][0] == "retrieval_explore"
    assert llm_payload["exploration_strategy"]["exploration_rate"] == 0.55
    assert llm_payload["action_family_priorities"] != base_payload["action_family_priorities"]

