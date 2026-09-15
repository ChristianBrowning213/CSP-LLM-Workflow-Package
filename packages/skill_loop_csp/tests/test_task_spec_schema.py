from __future__ import annotations

from sok_llm_orchestrator.orchestrator.task_spec import task_spec_from_query, validate_task_spec


def test_task_spec_from_query_defaults() -> None:
    spec = task_spec_from_query("Find plausible TiO2 structure")
    payload = spec.to_dict()
    validate_task_spec(payload)
    assert payload["composition_target"] == "TiO2"
    assert payload["solve_mode"] == "feasibility"


def test_task_spec_detects_missing_composition() -> None:
    spec = task_spec_from_query("Find plausible structure with corner sharing octahedra")
    assert spec.composition_target is None
    assert "composition_target:none" in spec.defaults_used


def test_task_spec_parses_property_bias_and_optimize_mode() -> None:
    spec = task_spec_from_query("For TiO2 prioritize high property X")
    assert spec.property_bias == "property_x"
    assert spec.solve_mode == "optimize"
