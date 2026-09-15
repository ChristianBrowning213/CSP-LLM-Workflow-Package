from __future__ import annotations

import json

from sok_llm_orchestrator.contracts.phase1_properties import Phase1PropertyResolutionError
from sok_llm_orchestrator.llm.client import LLMClient
from sok_llm_orchestrator.contracts.phase1_properties import resolve_phase1_property_request
from sok_llm_orchestrator.optimization.action_registry import legal_action_families
from sok_llm_orchestrator.optimization.plan_schema import OptimizationPlan, validate_optimization_plan


def _llm_priority_suggestion(
    *,
    llm_client: LLMClient | None,
    task_spec: dict[str, object],
    default_priorities: list[str],
    default_hypotheses: list[str],
    default_exploration_rate: float,
) -> dict[str, object]:
    if llm_client is None:
        return {}
    prompt = {
        "instruction": (
            "Provide plan suggestions for optimization as compact JSON only. "
            "Use legal families only. Schema: "
            "{\"action_family_priorities\":[...],\"initial_hypotheses\":[...],\"exploration_rate\":0.0-1.0,\"rationale\":\"...\"}."
        ),
        "task_spec": task_spec,
        "legal_action_families": legal_action_families(),
        "defaults": {
            "action_family_priorities": default_priorities,
            "initial_hypotheses": default_hypotheses,
            "exploration_rate": default_exploration_rate,
        },
    }
    try:
        response = llm_client.chat(
            messages=[
                {"role": "system", "content": "You are a cautious optimization planner."},
                {"role": "user", "content": json.dumps(prompt, sort_keys=True)},
            ]
        )
    except RuntimeError:
        return {}
    text = ""
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message", {})
        if isinstance(msg, dict):
            text = str(msg.get("content", ""))
    text = text.strip()
    if not text:
        return {}
    raw = text
    if "{" in raw and "}" in raw:
        raw = raw[raw.find("{") : raw.rfind("}") + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _merge_priorities(defaults: list[str], suggested: object) -> list[str]:
    legal = set(legal_action_families())
    ordered: list[str] = []
    if isinstance(suggested, list):
        for item in suggested:
            if not isinstance(item, str):
                continue
            value = item.strip()
            if value and value in legal and value not in ordered:
                ordered.append(value)
    for item in defaults:
        if item not in ordered:
            ordered.append(item)
    return ordered


def _merge_hypotheses(defaults: list[str], suggested: object) -> list[str]:
    values: list[str] = []
    if isinstance(suggested, list):
        for item in suggested:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    values.append(text)
    if values:
        return values[:4]
    return defaults


def build_optimization_plan(
    *,
    task_spec: dict[str, object],
    max_iterations: int,
    exploration_rate: float,
    stagnation_window: int,
    llm_client: LLMClient | None = None,
) -> OptimizationPlan:
    property_bias = task_spec.get("property_bias")
    composition = task_spec.get("composition_target") or "unspecified-composition"
    objective = "Improve QLIP objective under fixed composition/constraint contract."
    if isinstance(property_bias, str) and property_bias:
        try:
            resolved = resolve_phase1_property_request(property_bias, allow_small_wiring=True)
            property_phrase = f"{resolved.id} ({resolved.display_name})"
        except Phase1PropertyResolutionError:
            property_phrase = property_bias
        objective = (
            f"Improve QLIP objective for {composition} while biasing retrieval/SPP toward "
            f"{property_phrase} without claiming externally validated property gains."
        )

    hypotheses = [
        "Retrieval-conditioned SPP guidance can improve solver objective relative to baseline.",
        "Cell candidate policy influences feasibility and objective stability.",
    ]
    if task_spec.get("symmetry_request", {}).get("space_group"):
        hypotheses.append("Symmetry-constrained guidance can improve reproducibility if infeasibility is controlled.")

    llm_suggestion = _llm_priority_suggestion(
        llm_client=llm_client,
        task_spec=task_spec,
        default_priorities=[
            "guided_exploit",
            "retrieval_explore",
            "cell_policy",
            "baseline_control",
        ],
        default_hypotheses=hypotheses,
        default_exploration_rate=float(exploration_rate),
    )
    merged_exploration = float(exploration_rate)
    if isinstance(llm_suggestion.get("exploration_rate"), (int, float)):
        llm_rate = float(llm_suggestion["exploration_rate"])
        if 0.0 <= llm_rate <= 1.0:
            merged_exploration = llm_rate

    plan = OptimizationPlan(
        objective_target=objective,
        initial_hypotheses=_merge_hypotheses(hypotheses, llm_suggestion.get("initial_hypotheses")),
        action_family_priorities=_merge_priorities(
            [
                "guided_exploit",
                "retrieval_explore",
                "cell_policy",
                "baseline_control",
            ],
            llm_suggestion.get("action_family_priorities"),
        ),
        exploration_strategy={
            "policy": "epsilon_greedy",
            "exploration_rate": merged_exploration,
        },
        stopping_criteria={
            "max_iterations": int(max_iterations),
            "stagnation_window": int(stagnation_window),
            "target_threshold": None,
        },
        fallback_strategy=[
            "fallback_to_policy_top_candidate",
            "reduce_guidance_or_broaden_retrieval_after_repeated_failures",
        ],
        escalation_conditions=[
            "repeated_infeasibility",
            "stagnation",
            "action_family_ambiguity",
        ],
    )
    validate_optimization_plan(plan.to_dict())
    return plan
