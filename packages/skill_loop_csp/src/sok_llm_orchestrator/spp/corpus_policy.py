from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Any

from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle


@dataclass(slots=True)
class SppCorpusManifest:
    schema_version: str
    strategy: str
    retrieval_id: str
    selected_ids: list[str]
    weights: dict[str, float]
    metadata: dict[str, Any]
    content_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "strategy": self.strategy,
            "retrieval_id": self.retrieval_id,
            "selected_ids": self.selected_ids,
            "weights": self.weights,
            "metadata": self.metadata,
            "content_hash": self.content_hash,
        }


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def summarize_corpus_exportability(
    retrieval: RetrievalBundle,
    selected_ids: list[str],
) -> dict[str, Any]:
    row_by_id: dict[str, dict[str, Any]] = {}
    for row in retrieval.items:
        if not isinstance(row, dict):
            continue
        structure_id = row.get("structure_id")
        if isinstance(structure_id, str) and structure_id:
            row_by_id[structure_id] = row

    exportable_ids: list[str] = []
    blocked_ids: list[str] = []
    missing_export_ids: list[str] = []
    for structure_id in selected_ids:
        row = row_by_id.get(str(structure_id))
        artifacts = row.get("artifacts") if isinstance(row, dict) else {}
        if not isinstance(artifacts, dict):
            artifacts = {}
        export_status = str(artifacts.get("cif_export_status", "")).strip().lower()
        export_path = str(artifacts.get("cif_export_path", "")).strip()
        if export_status == "exported" and export_path:
            exportable_ids.append(str(structure_id))
        elif export_status == "blocked":
            blocked_ids.append(str(structure_id))
        else:
            missing_export_ids.append(str(structure_id))

    return {
        "selected_count": len(selected_ids),
        "exportable_count": len(exportable_ids),
        "blocked_count": len(blocked_ids),
        "missing_export_count": len(missing_export_ids),
        "exportable_ids": exportable_ids,
        "blocked_ids": blocked_ids,
        "missing_export_ids": missing_export_ids,
        "fit_ready": bool(exportable_ids),
    }


def choose_export_ready_corpus_candidate(
    retrieval: RetrievalBundle,
    candidates: list[dict[str, Any]],
    selected_index: int,
) -> tuple[int, dict[str, Any], list[dict[str, Any]]]:
    candidate_rows: list[dict[str, Any]] = []
    for idx, candidate in enumerate(candidates):
        manifest = candidate.get("manifest") if isinstance(candidate, dict) else {}
        if not isinstance(manifest, dict):
            manifest = {}
        selected_ids = manifest.get("selected_ids", [])
        if not isinstance(selected_ids, list):
            selected_ids = []
        exportability = summarize_corpus_exportability(
            retrieval,
            [str(item) for item in selected_ids if isinstance(item, str)],
        )
        row = dict(candidate) if isinstance(candidate, dict) else {"candidate_id": f"candidate:{idx}"}
        row["exportability"] = exportability
        candidate_rows.append(row)

    selected_index = max(0, min(int(selected_index), max(0, len(candidate_rows) - 1)))
    requested = candidate_rows[selected_index] if candidate_rows else {}
    requested_exportable = int(requested.get("exportability", {}).get("exportable_count", 0) or 0)
    if requested_exportable > 0:
        return (
            selected_index,
            {
                "selection_reason": "requested_candidate_export_ready",
                "requested_candidate_id": requested.get("candidate_id"),
                "selected_candidate_id": requested.get("candidate_id"),
            },
            candidate_rows,
        )

    for idx, candidate in enumerate(candidate_rows):
        exportability = candidate.get("exportability", {})
        if int(exportability.get("exportable_count", 0) or 0) > 0:
            return (
                idx,
                {
                    "selection_reason": "fallback_export_ready_candidate",
                    "requested_candidate_id": requested.get("candidate_id"),
                    "selected_candidate_id": candidate.get("candidate_id"),
                },
                candidate_rows,
            )

    return (
        selected_index,
        {
            "selection_reason": "no_export_ready_candidate_available",
            "requested_candidate_id": requested.get("candidate_id"),
            "selected_candidate_id": requested.get("candidate_id"),
        },
        candidate_rows,
    )


def stage_export_ready_cifs(
    retrieval: RetrievalBundle,
    selected_ids: list[str],
    out_dir: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    row_by_id: dict[str, dict[str, Any]] = {}
    for row in retrieval.items:
        if not isinstance(row, dict):
            continue
        structure_id = row.get("structure_id")
        if isinstance(structure_id, str) and structure_id:
            row_by_id[structure_id] = row

    staged: list[dict[str, Any]] = []
    blocked_ids: list[str] = []
    missing_export_ids: list[str] = []
    for index, structure_id in enumerate(selected_ids):
        row = row_by_id.get(str(structure_id))
        artifacts = row.get("artifacts") if isinstance(row, dict) else {}
        if not isinstance(artifacts, dict):
            artifacts = {}
        export_status = str(artifacts.get("cif_export_status", "")).strip().lower()
        export_path = str(artifacts.get("cif_export_path", "")).strip()
        if export_status == "exported" and export_path and Path(export_path).exists():
            source = Path(export_path)
            target = out_dir / f"{index + 1:03d}_{source.name}"
            shutil.copy2(source, target)
            staged.append(
                {
                    "structure_id": str(structure_id),
                    "source_path": str(source),
                    "staged_path": str(target),
                }
            )
        elif export_status == "blocked":
            blocked_ids.append(str(structure_id))
        else:
            missing_export_ids.append(str(structure_id))
    return {
        "staged_count": len(staged),
        "staged_items": staged,
        "blocked_ids": blocked_ids,
        "missing_export_ids": missing_export_ids,
    }


def select_corpus_manifest(
    retrieval: RetrievalBundle,
    strategy: str,
    top_k: int = 5,
    property_key: str | None = None,
) -> SppCorpusManifest:
    items = list(retrieval.items)
    missing_property = 0
    filtered_for_property = 0
    if strategy == "top_k":
        chosen = items[:top_k]
    elif strategy == "composition_tight":
        chosen = [row for row in items if "composition" in row.get("why_returned", "").lower()][:top_k] or items[:top_k]
    elif strategy == "family_biased":
        chosen = [row for row in items if "family" in row.get("why_returned", "").lower()][:top_k] or items[:top_k]
    elif strategy == "property_biased":
        if not property_key:
            raise ValueError("property_key is required for property_biased strategy.")
        scored_rows: list[tuple[float, dict[str, Any]]] = []
        for row in items:
            metadata = row.get("property_metadata")
            if not isinstance(metadata, dict):
                missing_property += 1
                continue
            if property_key not in metadata:
                missing_property += 1
                continue
            try:
                value = float(metadata[property_key])
            except (TypeError, ValueError):
                missing_property += 1
                continue
            filtered_for_property += 1
            scored_rows.append((value, row))
        if not scored_rows:
            raise ValueError(f"No retrieval rows contain numeric metadata for property key '{property_key}'.")
        chosen = [row for _, row in sorted(scored_rows, key=lambda pair: pair[0], reverse=True)[:top_k]]
    else:
        raise ValueError(f"Unsupported corpus strategy: {strategy}")

    selected_ids = [str(item["structure_id"]) for item in chosen]
    weights = {sid: float(max(top_k - idx, 1)) for idx, sid in enumerate(selected_ids)}
    payload = {
        "schema_version": "spp.corpus_manifest.v1",
        "strategy": strategy,
        "retrieval_id": retrieval.retrieval_id,
        "selected_ids": selected_ids,
        "weights": weights,
        "metadata": {
            "item_count": len(selected_ids),
            "property_key": property_key,
            "property_rows_used": filtered_for_property,
            "property_rows_missing": missing_property,
        },
    }
    return SppCorpusManifest(content_hash=_hash_payload(payload), **payload)
