from __future__ import annotations

from sok_llm_orchestrator.retrieval.fusion import fuse_results


def test_retrieval_fusion_hybrid() -> None:
    metadata = [
        {
            "structure_id": "mp-1",
            "provenance": "db",
            "scores": {"score": 0.8},
            "modality": "metadata",
            "identity": None,
            "cell_hint": None,
            "why_returned": "metadata",
        }
    ]
    fingerprint = [
        {
            "structure_id": "mp-1",
            "provenance": "db",
            "scores": {"score": 0.5},
            "modality": "fingerprint",
            "identity": None,
            "cell_hint": None,
            "why_returned": "fingerprint",
        }
    ]
    bundle = fuse_results("hybrid", metadata_items=metadata, fingerprint_items=fingerprint)
    assert bundle.mode == "hybrid"
    assert bundle.items[0]["scores"]["score"] > 0
