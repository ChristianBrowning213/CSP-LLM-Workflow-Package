from __future__ import annotations

from sok_llm_orchestrator.contracts.qlip_builders_v2 import build_solve_request_v2
from sok_llm_orchestrator.orchestrator.cell_selection import default_cell_candidates
from sok_llm_orchestrator.orchestrator.task_spec import task_spec_from_query
from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle


def _retrieval() -> RetrievalBundle:
    return RetrievalBundle(retrieval_id="r-linear", mode="metadata", fusion_notes=[], items=[])


def test_phase1_linear_property_proxy_maps_to_qlip_objective_family() -> None:
    spec = task_spec_from_query("TiO2 optimize high qlip.native.linear_property_proxy")
    req, meta = build_solve_request_v2(
        spec,
        default_cell_candidates(),
        _retrieval(),
        None,
        guidance_mode="none",
    )
    objective = req["problem"]["objective"]
    assert objective["type"] == "linear_property"
    assert objective["linear_property"]["kind"] == "occupancy_linear"
    assert objective["linear_property"]["terms"] == [
        {"species": "Ti", "coefficient": 1.0},
        {"species": "O", "coefficient": 1.0},
    ]
    assert meta["qlip_objective"] == objective
