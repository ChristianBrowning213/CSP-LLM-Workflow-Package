from __future__ import annotations

from sok_llm_orchestrator.orchestrator.clarification_policy import classify_missing_fields
from sok_llm_orchestrator.orchestrator.task_spec import task_spec_from_query


def test_clarification_policy_classifies_missing() -> None:
    spec = task_spec_from_query("Find plausible structure with octahedra")
    decision = classify_missing_fields(spec)
    assert "composition_target" in decision.hard_required
    assert decision.prompts


def test_clarification_policy_defaultable_symmetry() -> None:
    spec = task_spec_from_query("TiO2 rediscover known phase")
    decision = classify_missing_fields(spec)
    assert "symmetry_request.space_group" in decision.important_defaultable
