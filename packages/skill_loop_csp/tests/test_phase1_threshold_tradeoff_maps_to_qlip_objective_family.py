from __future__ import annotations

from sok_llm_orchestrator.contracts.qlip_builders_v2 import build_solve_request_v2
from sok_llm_orchestrator.orchestrator.cell_selection import default_cell_candidates
from sok_llm_orchestrator.orchestrator.task_spec import task_spec_from_query
from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle


def _retrieval() -> RetrievalBundle:
    return RetrievalBundle(retrieval_id="r-threshold", mode="metadata", fusion_notes=[], items=[])


def test_phase1_threshold_tradeoff_maps_to_qlip_objective_family() -> None:
    spec = task_spec_from_query("TiO2 optimize high qlip.native.threshold_tradeoff")
    req, meta = build_solve_request_v2(
        spec,
        default_cell_candidates(),
        _retrieval(),
        None,
        guidance_mode="none",
    )
    objective = req["problem"]["objective"]
    assert objective["type"] == "threshold_tradeoff"
    assert objective["linear_property"]["kind"] == "occupancy_linear"
    assert objective["threshold"] == {"operator": ">=", "value": 0.0}
    assert objective["base"] == {"type": "spp_energy"}
    assert objective["property_weight"] == 1.0
    assert meta["qlip_objective"] == objective
