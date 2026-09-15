from __future__ import annotations

from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle, validate_retrieval_bundle


def test_retrieval_bundle_schema() -> None:
    bundle = RetrievalBundle(
        retrieval_id="r1",
        mode="metadata",
        fusion_notes=[],
        items=[
            {
                "structure_id": "mp-1",
                "provenance": "crystaldb",
                "scores": {"score": 0.9},
                "modality": "metadata",
                "identity": None,
                "cell_hint": None,
                "why_returned": "composition match",
            }
        ],
    )
    validate_retrieval_bundle(bundle.to_dict())
    assert bundle.content_hash
