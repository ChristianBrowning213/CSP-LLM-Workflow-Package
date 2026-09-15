from __future__ import annotations

import uuid
from typing import Any

from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle, validate_retrieval_bundle


def _index_by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item["structure_id"]): item for item in items}


def fuse_results(
    mode: str,
    metadata_items: list[dict[str, Any]] | None = None,
    text_items: list[dict[str, Any]] | None = None,
    fingerprint_items: list[dict[str, Any]] | None = None,
    weights: dict[str, float] | None = None,
) -> RetrievalBundle:
    if mode in {"metadata", "text", "fingerprint"}:
        source = {
            "metadata": metadata_items or [],
            "text": text_items or [],
            "fingerprint": fingerprint_items or [],
        }[mode]
        bundle = RetrievalBundle(
            retrieval_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{mode}:{len(source)}")),
            mode=mode,
            items=source,
            fusion_notes=[f"single_mode:{mode}"],
        )
        validate_retrieval_bundle(bundle.to_dict())
        return bundle

    weights = weights or {"metadata": 0.5, "text": 0.2, "fingerprint": 0.3}
    combined: dict[str, dict[str, Any]] = {}
    sources = [
        ("metadata", metadata_items or []),
        ("text", text_items or []),
        ("fingerprint", fingerprint_items or []),
    ]
    for modality, items in sources:
        for item in items:
            sid = str(item["structure_id"])
            score = float(item.get("scores", {}).get("score", 0.0))
            if sid not in combined:
                combined[sid] = {
                    "structure_id": sid,
                    "provenance": str(item.get("provenance", modality)),
                    "scores": {"score": 0.0},
                    "modality": "hybrid",
                    "identity": item.get("identity"),
                    "cell_hint": item.get("cell_hint"),
                    "why_returned": "hybrid_fusion",
                }
            combined[sid]["scores"]["score"] += score * float(weights.get(modality, 0.0))
    ranked = sorted(combined.values(), key=lambda row: row["scores"]["score"], reverse=True)
    bundle = RetrievalBundle(
        retrieval_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"hybrid:{len(ranked)}")),
        mode="hybrid",
        items=ranked,
        fusion_notes=[f"weights:{weights}"],
    )
    validate_retrieval_bundle(bundle.to_dict())
    return bundle
