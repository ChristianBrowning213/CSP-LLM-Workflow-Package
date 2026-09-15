from __future__ import annotations

from sok_llm_orchestrator.contracts.phase1_properties import (
    list_phase1_property_entries,
    phase1_property_table,
    validate_phase1_property_registry,
)


def test_phase1_registry_contains_expected_entries() -> None:
    validate_phase1_property_registry()
    ids = {item.id for item in list_phase1_property_entries(include_small_wiring=True)}
    assert "qlip.objective.energy_proxy" in ids
    assert "qlip.property.property_x_estimate" in ids
    assert "spp.guidance.energy_spp_term" in ids
    assert "qlip.native.density_packing_proxy" in ids
    assert "qlip.native.linear_property_proxy" in ids
    assert "qlip.native.threshold_tradeoff" in ids


def test_phase1_registry_entry_metadata_shape() -> None:
    rows = phase1_property_table(include_small_wiring=True)
    for row in rows:
        assert isinstance(row.get("id"), str) and row["id"]
        assert isinstance(row.get("display_name"), str) and row["display_name"]
        assert row.get("source_system") in {"qlip_native", "spp_native", "hybrid"}
        assert row.get("formulation_type") in {"objective", "threshold", "constraint", "guidance"}
        assert row.get("optimization_direction") in {"minimize", "maximize", "bounded", "feasibility"}
        assert row.get("implementation_status") in {"implemented_now", "small_wiring_needed"}
        assert isinstance(row.get("required_inputs"), list) and row["required_inputs"]
        assert isinstance(row.get("notes"), str) and row["notes"]


def test_phase1_registry_reports_implemented_subset() -> None:
    implemented = list_phase1_property_entries(include_small_wiring=False)
    ids = {item.id for item in implemented}
    assert "qlip.objective.energy_proxy" in ids
    assert "qlip.property.property_x_estimate" in ids
    assert "spp.guidance.energy_spp_term" in ids
    assert "qlip.native.density_packing_proxy" in ids
    assert "qlip.native.linear_property_proxy" in ids
    assert "qlip.native.threshold_tradeoff" in ids
