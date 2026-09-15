from __future__ import annotations

from typing import Any

from sok_llm_orchestrator.orchestrator.clarification_policy import classify_missing_fields
from sok_llm_orchestrator.orchestrator.planner import build_run_plan
from sok_llm_orchestrator.orchestrator.plan_schema import validate_run_plan
from sok_llm_orchestrator.orchestrator.task_spec import task_spec_from_payload, task_spec_from_query


def run_intake_stage(
    query: str | None,
    plan_overrides: dict[str, Any] | None = None,
    *,
    task_spec_payload: dict[str, Any] | None = None,
    strict_phase1_benchmark_mode: bool = False,
) -> tuple[dict, dict, dict]:
    if task_spec_payload is not None:
        task_spec = task_spec_from_payload(
            task_spec_payload,
            strict_phase1_benchmark_mode=bool(strict_phase1_benchmark_mode),
        )
    else:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query is required when task_spec_payload is not provided.")
        task_spec = task_spec_from_query(query, strict_phase1_benchmark_mode=strict_phase1_benchmark_mode)
    clarifications = classify_missing_fields(task_spec)
    plan = build_run_plan(task_spec, deterministic=True).to_dict()
    if plan_overrides:
        for key, value in plan_overrides.items():
            if key in plan and key != "schema_version":
                plan[key] = value
        validate_run_plan(plan)
    return (
        task_spec.to_dict(),
        plan,
        {
            "hard_required": clarifications.hard_required,
            "important_defaultable": clarifications.important_defaultable,
            "optional": clarifications.optional,
            "prompts": clarifications.prompts,
        },
    )
