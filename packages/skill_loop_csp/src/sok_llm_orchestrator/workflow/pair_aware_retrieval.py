"""Deterministic same-family pair-support augmentation for request SPP corpora."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Iterable


def _candidate_rank(candidate: dict[str, Any], priority: set[str]) -> tuple[Any, ...]:
    supported = set(str(pair) for pair in candidate.get("supported_pairs", [])) & priority
    observations = candidate.get("observation_counts", {})
    observation_total = sum(int(observations.get(pair, 0)) for pair in supported)
    semantic_rank = candidate.get("semantic_rank")
    return (
        -len(supported),
        -observation_total,
        int(semantic_rank) if semantic_rank is not None else 10**9,
        str(candidate.get("structure_id", "")),
    )


def select_pair_augmentation(
    *, candidates: Iterable[dict[str, Any]], selected_structure_ids: Iterable[str],
    priority_pairs: Iterable[str], maximum_additions: int, coverage_only: bool,
) -> list[dict[str, Any]]:
    """Select deterministic real-support candidates without fabricating pairs.

    ``coverage_only`` stops once each priority pair has at least one newly
    selected contributor.  Quality augmentation leaves the priority set fixed
    and fills the requested bounded batch.
    """
    selected_ids = {str(value) for value in selected_structure_ids}
    remaining = {str(value) for value in priority_pairs}
    pool = [dict(row) for row in candidates if str(row.get("structure_id", "")) not in selected_ids]
    chosen: list[dict[str, Any]] = []
    for _ in range(max(0, int(maximum_additions))):
        priority = remaining if coverage_only else {str(value) for value in priority_pairs}
        if not priority:
            break
        eligible = [row for row in pool if set(str(pair) for pair in row.get("supported_pairs", [])) & priority]
        if not eligible:
            break
        best = min(eligible, key=lambda row: _candidate_rank(row, priority))
        supported = sorted(set(str(pair) for pair in best.get("supported_pairs", [])) & priority, key=str.lower)
        chosen.append({**best, "selection_pairs": supported})
        pool.remove(best)
        selected_ids.add(str(best.get("structure_id", "")))
        if coverage_only:
            remaining.difference_update(supported)
    return chosen


def build_family_pair_inventory(
    *, crystal_root: Path, dataset_dir: Path, formula: str, cutoff: float,
    excluded_structure_ids: Iterable[str], semantic_retrieval: dict[str, Any], work_dir: Path,
) -> list[dict[str, Any]]:
    """Measure real periodic support for every non-target family structure."""
    from spp_maker_qlip.required_pair_extraction import collect_required_pair_distances

    excluded = {str(value) for value in excluded_structure_ids}
    payload = json.loads((Path(dataset_dir) / "accepted.json").read_text(encoding="utf-8"))
    rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
    retrieval_by_id = {
        str(row.get("structure_id", "")): {
            "semantic_rank": int(row.get("rank", index)),
            "semantic_score": float(row.get("score", row.get("retrieval_score", 0.0))),
        }
        for index, row in enumerate(semantic_retrieval.get("selected", []), start=1)
    }
    corpus = Path(work_dir) / "pair_inventory_cifs"
    corpus.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, dict[str, Any]] = {}
    for row in rows:
        structure_id = str(row["structure_id"])
        if structure_id in excluded:
            continue
        raw_path = row.get("structure_bundle", {}).get("paths", {}).get("primitive")
        source = Path(str(raw_path))
        if not source.is_absolute():
            source = Path(crystal_root) / source
        if not source.is_file():
            continue
        destination = corpus / f"{structure_id}.cif"
        if not destination.is_file():
            shutil.copy2(source, destination)
        metadata[structure_id] = {
            "structure_id": structure_id,
            "material_id": str(row.get("material_id", "")),
            "candidate_key": str(row.get("candidate_key", "")),
            "cif_path": str(destination.resolve()),
            **retrieval_by_id.get(structure_id, {"semantic_rank": None, "semantic_score": None}),
        }
    diagnostics = collect_required_pair_distances(corpus, formula=formula, cutoff=float(cutoff))
    output: list[dict[str, Any]] = []
    for cif in diagnostics.get("cifs", []):
        structure_id = Path(str(cif["file"])).stem
        if structure_id not in metadata:
            continue
        pair_rows = cif.get("geometric_pairs_within_cutoff", {})
        output.append({
            **metadata[structure_id],
            "supported_pairs": sorted(pair_rows, key=str.lower),
            "observation_counts": {pair: int(values["count"]) for pair, values in pair_rows.items()},
            "distance_ranges": {
                pair: {"minimum_A": values["min_distance"], "maximum_A": values["max_distance"]}
                for pair, values in pair_rows.items()
            },
        })
    return sorted(output, key=lambda row: (row["semantic_rank"] is None, row["semantic_rank"] or 10**9, row["structure_id"]))


def append_augmentation_to_retrieval(
    retrieval: dict[str, Any], additions: Iterable[dict[str, Any]], *, export_dir: Path,
) -> dict[str, Any]:
    """Append auditable augmentation CIFs in the shape expected by evidence assembly."""
    selected = [dict(row) for row in retrieval.get("selected", [])]
    existing = {str(row.get("structure_id", "")) for row in selected}
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    for addition in additions:
        structure_id = str(addition["structure_id"])
        if structure_id in existing:
            continue
        source = Path(str(addition["cif_path"]))
        destination = export_dir / f"{structure_id}.cif"
        if not destination.is_file():
            shutil.copy2(source, destination)
        selected.append({
            "structure_id": structure_id,
            "rank": 100000 + len(selected) + 1,
            "score": float(addition.get("semantic_score") or 0.0),
            "retrieval_score": float(addition.get("semantic_score") or 0.0),
            "source_id": addition.get("material_id"),
            "cif_export": {"status": "exported", "path": str(destination.resolve())},
            "selection_source": "same_family_pair_augmentation",
            "selection_pairs": list(addition.get("selection_pairs", [])),
        })
        existing.add(structure_id)
    return {**retrieval, "selected": selected}


def actual_pair_structure_counts(
    selected_structure_ids: Iterable[str], inventory: Iterable[dict[str, Any]], required_pairs: Iterable[str],
) -> dict[str, int]:
    selected = {str(value) for value in selected_structure_ids}
    counts = {str(pair): 0 for pair in required_pairs}
    for row in inventory:
        if str(row.get("structure_id", "")) not in selected:
            continue
        for pair in set(str(value) for value in row.get("supported_pairs", [])) & set(counts):
            counts[pair] += 1
    return counts


__all__ = [
    "actual_pair_structure_counts", "append_augmentation_to_retrieval",
    "build_family_pair_inventory", "select_pair_augmentation",
]
