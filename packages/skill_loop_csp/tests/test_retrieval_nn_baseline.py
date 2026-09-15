from __future__ import annotations

from sok_llm_orchestrator.baselines.retrieval_nn import run_retrieval_nn_baseline
from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle


def test_retrieval_nn_baseline_selects_top_hit() -> None:
    retrieval = RetrievalBundle(
        retrieval_id="r1",
        mode="metadata",
        fusion_notes=[],
        items=[
            {
                "structure_id": "mp-1",
                "provenance": "db",
                "scores": {"score": 0.9},
                "modality": "metadata",
                "identity": None,
                "cell_hint": None,
                "why_returned": "match",
            }
        ],
    )
    out = run_retrieval_nn_baseline(retrieval)
    assert out["ok"] is True
    assert out["selected_structure_id"] == "mp-1"
