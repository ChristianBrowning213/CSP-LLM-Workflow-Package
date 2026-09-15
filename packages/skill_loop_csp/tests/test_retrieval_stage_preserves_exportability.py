from __future__ import annotations

from sok_llm_orchestrator.orchestrator.stages.retrieval import run_retrieval_stage


def test_retrieval_stage_preserves_neighbor_exportability_metadata() -> None:
    payload = {
        "neighbors": [
            {
                "structure_id": "mp-1",
                "score": 0.9,
                "property_metadata": {"property_x": 0.8},
                "provenance": {"allow_export": 0},
                "cif_export": {"status": "blocked", "error": "policy_blocked"},
            },
            {
                "structure_id": "mp-2",
                "score": 0.8,
                "property_metadata": {"property_x": 0.7},
                "provenance": {"allow_export": 1},
                "cif_export": {"status": "exported", "path": "C:/tmp/mp-2.cif"},
            },
        ]
    }
    bundle = run_retrieval_stage(payload, mode="metadata", property_key="property_x")
    first = bundle.items[0]["artifacts"]
    second = bundle.items[1]["artifacts"]
    assert first["cif_export_status"] == "blocked"
    assert first["cif_export_error"] == "policy_blocked"
    assert first["allow_export"] == 0
    assert second["cif_export_status"] == "exported"
    assert second["cif_export_path"] == "C:/tmp/mp-2.cif"
    assert second["allow_export"] == 1
