from __future__ import annotations

from sok_llm_orchestrator.orchestrator.task_spec import task_spec_from_query


def test_phase2_task_spec_distinguishes_native_vs_external_targets() -> None:
    spec = task_spec_from_query(
        "TiO2 optimize high density with external predictor "
        "phase2.external.pymatgen_composition_descriptor"
    )
    assert spec.qlip_objective == {"type": "density_packing", "proxy": "pair_distance_packing"}
    assert spec.property_bias is None
    assert spec.external_predictor_targets == [
        {
            "schema_version": "phase2.external_predictor_request.v1",
            "predictor_id": "phase2.external.pymatgen_composition_descriptor",
            "target": "mean_atomic_number",
            "use": "reporting",
            "value_state": "raw",
        }
    ]
