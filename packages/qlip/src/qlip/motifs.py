"""
Helpers for loading motif templates/instances produced by `tools.generators.motifs`.

This module keeps the loader logic close to the allocator runtime so the
allocation layer can hydrate motifs on demand without re-implementing the JSON
parsing every time we add emitters.
"""

from __future__ import annotations


from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json

from functools import lru_cache
from typing import Dict, Iterable, List, Sequence, Tuple

MotifInstance = Tuple[int, List[Tuple[str, int]]]


@dataclass(frozen=True)
class MotifRecord:
    """In-memory summary of a motif relevant to the allocator."""

    name: str
    anchor: str
    instances: Tuple[MotifInstance, ...]


def _as_path(path: Path | str | None) -> Path:
    if path is None:
        raise ValueError("A valid path is required for motif artifacts.")
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    return p


@lru_cache(maxsize=None)
def _load_raw_artifacts(motif_path: Path, instance_path: Path) -> Tuple[List[dict], Dict[str, List[Sequence]]]:
    motifs = json.loads(motif_path.read_text())
    instances = json.loads(instance_path.read_text())
    return motifs, instances


def load_motif_catalog(
    artifact_dir: str | Path,
    allowed_species: Iterable[str],
    include: Iterable[str] | None = None,
) -> Dict[str, MotifRecord]:
    """
    Load motifs + snapped instances, filtering by desired species and (optionally) name.

    Parameters
    ----------
    artifact_dir
        Directory containing ``motifs.json`` and ``instances.json`` produced by the generators.
    allowed_species
        Species present in the allocator stoichiometry. Motifs requiring atoms outside
        this set are discarded so we never introduce impossible assignments.
    include
        Optional whitelist of motif names to keep. If ``None`` all compatible motifs survive.
    """

    artifact_root = _as_path(artifact_dir)
    motif_path = artifact_root / "motifs.json"
    inst_path = artifact_root / "instances.json"
    motifs, insts = _load_raw_artifacts(motif_path.resolve(), inst_path.resolve())

    allowed = {str(s) for s in allowed_species}
    whitelist = {str(k) for k in include} if include else None

    catalog: Dict[str, MotifRecord] = {}
    for motif in motifs:
        name = str(motif.get("name"))
        anchor = str(motif.get("anchor"))
        if whitelist and name not in whitelist:
            continue
        if anchor not in allowed:
            continue

        raw_instances = insts.get(name, [])
        parsed: List[MotifInstance] = []
        for raw in raw_instances:
            if not isinstance(raw, (list, tuple)) or len(raw) != 2:
                continue
            anchor_idx, neighs = raw
            try:
                anchor_idx = int(anchor_idx)
            except (TypeError, ValueError):
                continue

            cleaned: List[Tuple[str, int]] = []
            skip_instance = False
            for entry in neighs:
                if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                    skip_instance = True
                    break
                species, site_idx = entry
                species = str(species)
                if species not in allowed:
                    skip_instance = True
                    break
                try:
                    site = int(site_idx)
                except (TypeError, ValueError):
                    skip_instance = True
                    break
                cleaned.append((species, site))

            if not skip_instance:
                parsed.append((anchor_idx, cleaned))

        if parsed:
            catalog[name] = MotifRecord(name=name, anchor=anchor, instances=tuple(parsed))

    return catalog


def compatible_subset(catalog: Dict[str, MotifRecord], site_count: int) -> Dict[str, MotifRecord]:
    """
    Filter instances to those fully contained within the available site index domain.

    Some artifact dumps include instances targeting a larger supercell than the
    current allocator run. This helper trims those out while keeping the catalog
    shape unchanged.
    """
    trimmed: Dict[str, MotifRecord] = {}
    for name, record in catalog.items():
        ok_instances: List[MotifInstance] = []
        for anchor_idx, neighs in record.instances:
            if anchor_idx < 0 or anchor_idx >= site_count:
                continue
            if any(site < 0 or site >= site_count for _, site in neighs):
                continue
            ok_instances.append((anchor_idx, list(neighs)))
        if ok_instances:
            trimmed[name] = MotifRecord(
                name=name,
                anchor=record.anchor,
                instances=tuple((anchor, list(neighs)) for anchor, neighs in ok_instances),
            )
    return trimmed

# ───────────────── Back-compat shim ─────────────────
def load_motifs(
    artifact_dir: str | Path,
    allowed_species: Iterable[str],
    include: Iterable[str] | None = None,
) -> Dict[str, MotifRecord]:
    """
    Backwards-compatible alias for older callers expecting `load_motifs`.
    Delegates to the new `load_motif_catalog`.
    """
    return load_motif_catalog(artifact_dir=artifact_dir, allowed_species=allowed_species, include=include)
