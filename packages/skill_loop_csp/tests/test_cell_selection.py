from __future__ import annotations

from sok_llm_orchestrator.orchestrator.cell_selection import select_cell_candidates
from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle


def test_cell_selection_retrieval_informed() -> None:
    retrieval = RetrievalBundle(
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
                "cell_hint": {"a": 4.7, "b": 4.7, "c": 3.1, "alpha": 90.0, "beta": 90.0, "gamma": 90.0},
                "why_returned": "composition match",
            }
        ],
    )
    out = select_cell_candidates("retrieval_informed", retrieval=retrieval)
    assert len(out) >= 2
    assert any(item.source == "retrieval" for item in out)
