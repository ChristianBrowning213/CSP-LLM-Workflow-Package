from __future__ import annotations

import uuid
from typing import Any

from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle, validate_retrieval_bundle


def run_retrieval_stage(
    crystal_csp_pack_payload: dict[str, Any],
    mode: str = "metadata",
    property_key: str | None = None,
) -> RetrievalBundle:
    neighbors = crystal_csp_pack_payload.get("neighbors", [])
    items = []
    for neighbor in neighbors:
        property_metadata = neighbor.get("property_metadata")
        if not isinstance(property_metadata, dict):
            property_metadata = None
        cif_export = neighbor.get("cif_export")
        if not isinstance(cif_export, dict):
            cif_export = {}
        provenance = neighbor.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        artifacts = {
            "cif_export_status": str(cif_export.get("status")) if cif_export.get("status") is not None else None,
            "cif_export_path": str(cif_export.get("path")) if isinstance(cif_export.get("path"), str) else None,
            "cif_export_error": str(cif_export.get("error")) if cif_export.get("error") is not None else None,
            "allow_export": provenance.get("allow_export"),
        }
        scores = {"score": float(neighbor.get("score", 0.0))}
        why_returned = "csp_pack_neighbor"
        if property_key and property_metadata is not None and property_key in property_metadata:
            try:
                scores[property_key] = float(property_metadata[property_key])
                why_returned = f"csp_pack_neighbor_property:{property_key}"
            except (TypeError, ValueError):
                pass
        items.append(
            {
                "structure_id": str(neighbor.get("structure_id", "unknown")),
                "provenance": "crystal.csp_pack",
                "scores": scores,
                "property_metadata": property_metadata,
                "artifacts": artifacts,
                "modality": mode if mode in {"metadata", "text", "fingerprint"} else "hybrid",
                "identity": None,
                "cell_hint": None,
                "why_returned": why_returned,
            }
        )
    bundle = RetrievalBundle(
        retrieval_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{mode}:{len(items)}")),
        mode=mode if mode in {"metadata", "text", "fingerprint"} else "hybrid",
        items=items,
        fusion_notes=["derived_from_crystal_csp_pack"],
    )
    validate_retrieval_bundle(bundle.to_dict())
    return bundle
