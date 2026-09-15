from __future__ import annotations

from sok_llm_orchestrator.optimization.preflight import preflight_from_query


def test_preflight_blocks_missing_composition() -> None:
    preflight = preflight_from_query("optimize with high property x")
    assert preflight.ready is False
    assert "composition_target" in preflight.unresolved_critical_fields
    assert preflight.questions


def test_preflight_ready_with_fixed_composition() -> None:
    preflight = preflight_from_query("TiO2 optimize high property x")
    assert preflight.ready is True
    assert not preflight.unresolved_critical_fields

