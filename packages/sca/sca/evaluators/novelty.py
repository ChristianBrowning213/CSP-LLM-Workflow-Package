"""Novelty checks against a reference structure corpus."""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass

import pandas as pd
from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Structure

from sca.evaluators.cif_parse import parse_cif
from sca.io import resolve_manifest_path
from sca.schemas import NoveltyResult


@dataclass(frozen=True)
class ReferenceLoadResult:
    structures: dict[str, Structure]
    loaded_count: int
    failed_count: int


def load_reference_structures(
    reference_folder: str | Path | None = None,
    reference_manifest: str | Path | None = None,
    path_col: str = "cif_path",
    id_col: str | None = None,
) -> dict[str, Structure]:
    return load_reference_structures_with_stats(
        reference_folder=reference_folder,
        reference_manifest=reference_manifest,
        path_col=path_col,
        id_col=id_col,
    ).structures


def load_reference_structures_with_stats(
    reference_folder: str | Path | None = None,
    reference_manifest: str | Path | None = None,
    path_col: str = "cif_path",
    id_col: str | None = None,
) -> ReferenceLoadResult:
    references: dict[str, Structure] = {}
    paths: list[tuple[str, Path]] = []

    if reference_folder:
        folder = Path(reference_folder)
        paths.extend((str(path), path) for path in sorted(folder.rglob("*.cif")))

    if reference_manifest:
        manifest = Path(reference_manifest)
        frame = pd.read_csv(manifest)
        if path_col not in frame.columns:
            raise ValueError(f"Reference manifest path column '{path_col}' not found")
        for index, row in frame.iterrows():
            path = resolve_manifest_path(row[path_col], manifest)
            ref_id = str(row[id_col]) if id_col and id_col in frame.columns else str(path)
            paths.append((ref_id, path))

    for ref_id, path in paths:
        structure, parsed = parse_cif(path)
        if parsed.parse_ok and structure is not None:
            references[ref_id] = structure
    return ReferenceLoadResult(
        structures=references,
        loaded_count=len(references),
        failed_count=len(paths) - len(references),
    )


def evaluate_novelty(
    structure: Structure,
    reference_structures: dict[str, Structure] | None,
    matcher: StructureMatcher | None = None,
) -> NoveltyResult:
    if not reference_structures:
        return NoveltyResult(novelty_checked=False)

    matcher = matcher or StructureMatcher(
        ltol=0.2,
        stol=0.3,
        angle_tol=5,
        primitive_cell=True,
        scale=True,
        attempt_supercell=True,
    )
    try:
        for ref_id, reference in reference_structures.items():
            if matcher.fit(structure, reference):
                return NoveltyResult(
                    novelty_checked=True,
                    nearest_reference_id=ref_id,
                    known_match=True,
                    novel_by_structure_matcher=False,
                )
        return NoveltyResult(
            novelty_checked=True,
            known_match=False,
            novel_by_structure_matcher=True,
        )
    except Exception as exc:
        return NoveltyResult(
            novelty_checked=True,
            novelty_error=f"{type(exc).__name__}: {exc}",
        )
