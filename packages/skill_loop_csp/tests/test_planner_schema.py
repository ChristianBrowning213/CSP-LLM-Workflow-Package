from __future__ import annotations

from sok_llm_orchestrator.orchestrator.plan_schema import validate_run_plan
from sok_llm_orchestrator.orchestrator.planner import build_run_plan
from sok_llm_orchestrator.orchestrator.task_spec import task_spec_from_query


def test_planner_emits_stable_plan() -> None:
    spec = task_spec_from_query("Rediscover TiO2 rutile with broad retrieval")
    plan = build_run_plan(spec, deterministic=True)
    payload = plan.to_dict()
    validate_run_plan(payload)
    assert payload["guidance_mode"] == "guidance_only"


def test_planner_determinism() -> None:
    spec = task_spec_from_query("TiO2")
    p1 = build_run_plan(spec, deterministic=True).to_dict()
    p2 = build_run_plan(spec, deterministic=True).to_dict()
    assert p1 == p2


def test_planner_uses_property_biased_corpus_when_property_requested() -> None:
    spec = task_spec_from_query("TiO2 optimize high property X")
    payload = build_run_plan(spec, deterministic=True).to_dict()
    assert payload["corpus_strategy"] == "property_biased"
