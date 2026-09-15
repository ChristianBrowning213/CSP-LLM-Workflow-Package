from __future__ import annotations

from typing import Any

from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle


def run_retrieval_nn_baseline(retrieval: RetrievalBundle) -> dict[str, Any]:
    if not retrieval.items:
        return {
            "schema_version": "baseline.retrieval_nn.v1",
            "ok": False,
            "reason": "no_items",
            "selected_structure_id": None,
        }
    top = retrieval.items[0]
    return {
        "schema_version": "baseline.retrieval_nn.v1",
        "ok": True,
        "selected_structure_id": top["structure_id"],
        "score": top.get("scores", {}).get("score"),
        "mode": retrieval.mode,
    }
