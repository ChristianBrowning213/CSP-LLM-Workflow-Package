"""Cubic native-cell volume strategies for the no-scaffold QLIP domain.

Pure, side-effect-free helpers.  For this first cell-size diagnostic ALL
THREE cell_mode conditions keep the candidate cell cubic
(``a == b == c``, all angles 90 deg) and the uniform-grid density frozen
at 8 -- matching the existing frozen native QLIP defaults.  The ONLY
scientific variable across cell_mode conditions is the physical edge
length ``a``, derived from a per-mode volume-per-atom (VPA) statistic.

This module knows nothing about QLIP wire schemas, SPP guidance, or
scaffolds -- it only resolves a cubic cell for a given target formula.

cell_mode values:

- ``native``: the existing frozen production default (a=b=c=3.9 A).
  Independent of formula/atom count.  This is the control condition.
- ``composition_scaled``: V_cell = N_target_atoms * GLOBAL_VPA, where
  GLOBAL_VPA is a single frozen constant derived from a broad,
  target-independent Crystal-DB corpus (see GLOBAL_VPA_A3_PER_ATOM and
  its provenance below).  No target-specific or target-family-specific
  statistics are used.
- ``retrieval_derived``: V_cell = N_target_atoms * VPA_request, where
  VPA_request is the median volume-per-atom over the SAME leakage-safe
  evidence cohort already assembled for request-SPP fitting (no second
  hidden retrieval).

``N_target_atoms`` is the literal atom count of the target formula as
passed to QLIP for the native (unscaled) candidate-site domain -- i.e.
``Composition(formula).num_atoms``, NOT a site-count-scaled formula.
The native/no-scaffold QLIP request always sends the raw target formula
(see ``runner.py`` :func:`ProductionWorkflowStages.solve`, where
``qlip_formula = task["formula"]`` whenever ``structure is None``), so
no additional site-count scaling factor applies here.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from pymatgen.core import Composition, Structure


CELL_MODES = ("native", "composition_scaled", "retrieval_derived")

NATIVE_CELL_A = 3.9
NATIVE_GRID_DENSITY = 8

# Frozen 2026-08-19 from a one-time preflight over the canonical general
# Crystal-DB corpus (mp_stable_10k_v1, the same corpus route_corpus() uses
# for any non-NASICON request).  See scripts/compute_corpus_vpa_stats.py
# and artifacts/Paper_results_native_cell_size_test_2026-08-19_155735/
# GLOBAL_VPA_PREFLIGHT.{json,md} for the full computation and provenance.
GLOBAL_VPA_A3_PER_ATOM = 17.986899303180298
GLOBAL_VPA_PROVENANCE = {
    "corpus_id": "mp_stable_10k_v1",
    "corpus_role": "canonical_general",
    "database_sha256": "a22acea31a0a6199b0c57785e6a07e250fe7bd42bd602393016f0a5947f00aeb",
    "included_count": 10000,
    "structure_count_total": 10000,
    "vpa_q1_A3_per_atom": 14.367535426047299,
    "vpa_q3_A3_per_atom": 24.842106827560478,
    "vpa_min_A3_per_atom": 6.160903789018464,
    "vpa_max_A3_per_atom": 122.8880281727645,
    "excluded_reduced_formulas": ("LiZr2(PO4)3", "Na3Ti2(PO4)3", "Na3Zr2Si2PO12"),
    "preflight_artifact": (
        "artifacts/Paper_results_native_cell_size_test_2026-08-19_155735/"
        "GLOBAL_VPA_PREFLIGHT.json"
    ),
}


@dataclass(frozen=True, slots=True)
class ResolvedCell:
    cell_mode: str
    a: float
    b: float
    c: float
    alpha: float
    beta: float
    gamma: float
    grid_density: int
    grid_spacing_A: float
    n_target_atoms: int
    vpa_source: str
    vpa_value: float | None
    cell_volume_A3: float
    provenance: dict[str, Any] = field(default_factory=dict)

    def lattice_dict(self) -> dict[str, Any]:
        return {
            "a": self.a, "b": self.b, "c": self.c,
            "alpha": self.alpha, "beta": self.beta, "gamma": self.gamma,
            "units": "angstrom",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_mode": self.cell_mode, "a": self.a, "b": self.b, "c": self.c,
            "alpha": self.alpha, "beta": self.beta, "gamma": self.gamma,
            "grid_density": self.grid_density, "grid_spacing_A": self.grid_spacing_A,
            "n_target_atoms": self.n_target_atoms, "vpa_source": self.vpa_source,
            "vpa_value_A3_per_atom": self.vpa_value, "cell_volume_A3": self.cell_volume_A3,
            "provenance": self.provenance,
        }


def n_target_atoms(formula: str) -> int:
    """Literal (unscaled) target formula atom count sent to native QLIP."""
    count = Composition(formula).num_atoms
    rounded = round(count)
    if abs(count - rounded) > 1e-9:
        raise ValueError(f"non-integral atom count for formula {formula!r}: {count}")
    return int(rounded)


def _cubic_edge(volume: float) -> float:
    if volume <= 0.0:
        raise ValueError(f"cell volume must be positive, got {volume}")
    return volume ** (1.0 / 3.0)


def evidence_vpa_records(evidence_selected: Iterable[Any]) -> tuple[dict[str, Any], ...]:
    """Compute per-structure VPA from the SAME leakage-safe evidence cohort.

    ``evidence_selected`` is ``SPPEvidenceBundle.selected`` -- the exact
    structures already assembled for request-SPP fitting.  No second
    retrieval is issued.
    """
    records: list[dict[str, Any]] = []
    for item in evidence_selected:
        structure = Structure.from_file(item.cif_path)
        volume = float(structure.volume)
        sites = len(structure)
        if sites <= 0 or volume <= 0.0:
            continue
        records.append({
            "structure_id": str(item.structure_id),
            "cif_path": str(item.cif_path),
            "cif_sha256": str(item.cif_sha256),
            "num_sites": int(sites),
            "volume_A3": volume,
            "vpa_A3_per_atom": volume / sites,
        })
    return tuple(records)


def resolve_native_cell(
    formula: str,
    *,
    cell_mode: str,
    grid_density: int = NATIVE_GRID_DENSITY,
    cell_volume_per_atom: float | None = None,
    evidence_vpa_records: tuple[dict[str, Any], ...] = (),
) -> ResolvedCell:
    """Resolve a cubic native-domain cell for one of the three frozen strategies.

    ``cell_volume_per_atom`` is an explicit user override; it must be
    ``None`` for the frozen nine-row scientific experiment (native and
    composition_scaled/retrieval_derived without an override are the only
    combinations exercised there).
    """
    if cell_mode not in CELL_MODES:
        raise ValueError(f"cell_mode must be one of {CELL_MODES}, got {cell_mode!r}")
    if grid_density <= 0:
        raise ValueError(f"grid_density must be positive, got {grid_density}")
    atoms = n_target_atoms(formula)

    if cell_mode == "native":
        if cell_volume_per_atom is not None:
            raise ValueError("cell_volume_per_atom override is not applicable to cell_mode='native'")
        a = NATIVE_CELL_A
        volume = a ** 3
        vpa_source = "native_frozen_default"
        vpa_value = None
        provenance: dict[str, Any] = {
            "strategy": "native",
            "note": "frozen production default; independent of formula/atom count",
        }
    elif cell_mode == "composition_scaled":
        vpa = GLOBAL_VPA_A3_PER_ATOM if cell_volume_per_atom is None else float(cell_volume_per_atom)
        volume = atoms * vpa
        a = _cubic_edge(volume)
        vpa_source = "global_vpa_frozen_constant" if cell_volume_per_atom is None else "explicit_override"
        vpa_value = vpa
        provenance = {"strategy": "composition_scaled", "vpa_source": vpa_source, "vpa_value_A3_per_atom": vpa}
        if cell_volume_per_atom is None:
            provenance["global_vpa_provenance"] = dict(GLOBAL_VPA_PROVENANCE)
    else:
        if cell_volume_per_atom is not None:
            raise ValueError("cell_volume_per_atom override is not applicable to cell_mode='retrieval_derived'")
        if not evidence_vpa_records:
            raise ValueError("retrieval_derived cell mode requires at least one evidence VPA record")
        values = sorted(float(record["vpa_A3_per_atom"]) for record in evidence_vpa_records)
        vpa = statistics.median(values)
        volume = atoms * vpa
        a = _cubic_edge(volume)
        vpa_source = "retrieval_evidence_median"
        vpa_value = vpa
        provenance = {
            "strategy": "retrieval_derived",
            "vpa_source": vpa_source,
            "vpa_value_A3_per_atom": vpa,
            "evidence_structure_count": len(evidence_vpa_records),
            "evidence_vpa_records": list(evidence_vpa_records),
        }

    return ResolvedCell(
        cell_mode=cell_mode, a=a, b=a, c=a, alpha=90.0, beta=90.0, gamma=90.0,
        grid_density=grid_density, grid_spacing_A=a / grid_density,
        n_target_atoms=atoms, vpa_source=vpa_source, vpa_value=vpa_value,
        cell_volume_A3=volume, provenance=provenance,
    )


__all__ = [
    "CELL_MODES", "NATIVE_CELL_A", "NATIVE_GRID_DENSITY",
    "GLOBAL_VPA_A3_PER_ATOM", "GLOBAL_VPA_PROVENANCE",
    "ResolvedCell", "n_target_atoms", "evidence_vpa_records", "resolve_native_cell",
]
