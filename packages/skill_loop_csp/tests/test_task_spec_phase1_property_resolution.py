from __future__ import annotations

from sok_llm_orchestrator.orchestrator.task_spec import task_spec_from_query


def test_task_spec_binds_canonical_phase1_objective_from_query_text() -> None:
    spec = task_spec_from_query(
        "Find a feasible TiO2 crystal. Composition fixed to TiO2. Keep symmetry unconstrained. "
        "Use retrieval and SPP guidance. Primary objective: qlip.objective.energy_proxy. "
        "Secondary preference: rutile-like."
    )
    assert spec.composition_target == "TiO2"
    assert spec.qlip_objective == {"type": "spp_energy"}
    assert spec.solve_mode == "feasibility"
    assert spec.symmetry_request.space_group is None
    assert spec.symmetry_request.hardness == "none"
    assert "qlip_objective_unbound:qlip.objective.energy_proxy" not in spec.defaults_used


def test_task_spec_keeps_supported_phase1_property_bias() -> None:
    spec = task_spec_from_query("For TiO2 prioritize high property X")
    assert spec.property_bias == "property_x"
    assert spec.solve_mode == "optimize"


def test_task_spec_preserves_unresolved_property_bias_with_diagnostic_note() -> None:
    spec = task_spec_from_query("For TiO2 prioritize high density")
    assert spec.property_bias is None
    assert spec.qlip_objective == {"type": "density_packing", "proxy": "pair_distance_packing"}
    assert "property_bias_unresolved:PHASE1_SMALL_WIRING_REQUIRED" not in spec.defaults_used
