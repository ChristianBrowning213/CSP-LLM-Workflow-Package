from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from ase import Atoms
from ase.geometry import get_distances
from ase.io import read


def _normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().capitalize()


def _normalize_pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((_normalize_symbol(a), _normalize_symbol(b))))


def load_structure(path) -> Atoms:
    return read(path)


def _mic_delta_frac(delta_frac: np.ndarray, pbc: np.ndarray) -> np.ndarray:
    wrapped = np.asarray(delta_frac, dtype=float).copy()
    for axis in range(3):
        if pbc[axis]:
            wrapped[axis] -= np.round(wrapped[axis])
    return wrapped


def _composition_counts(symbols: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for symbol in symbols:
        key = _normalize_symbol(symbol)
        counts[key] = counts.get(key, 0) + 1
    return counts


@dataclass(frozen=True)
class StructureMatch:
    mapping: list[tuple[int, int]]
    displacement_vectors: np.ndarray
    displacement_norms: np.ndarray


def match_structures(atoms_a: Atoms, atoms_b: Atoms) -> StructureMatch:
    symbols_a = [_normalize_symbol(symbol) for symbol in atoms_a.get_chemical_symbols()]
    symbols_b = [_normalize_symbol(symbol) for symbol in atoms_b.get_chemical_symbols()]
    if len(symbols_a) != len(symbols_b):
        raise ValueError(
            f"Cannot match structures with different atom counts: {len(symbols_a)} != {len(symbols_b)}"
        )
    if _composition_counts(symbols_a) != _composition_counts(symbols_b):
        raise ValueError("Cannot match structures with different compositions")

    frac_a = atoms_a.get_scaled_positions(wrap=True)
    frac_b = atoms_b.get_scaled_positions(wrap=True)
    cell_avg = 0.5 * (atoms_a.get_cell().array + atoms_b.get_cell().array)
    pbc = np.logical_and(np.asarray(atoms_a.get_pbc(), dtype=bool), np.asarray(atoms_b.get_pbc(), dtype=bool))

    mapping: list[tuple[int, int]] = []
    disp_vectors = np.zeros((len(symbols_a), 3), dtype=float)
    disp_norms = np.zeros(len(symbols_a), dtype=float)

    if symbols_a == symbols_b:
        for i in range(len(symbols_a)):
            delta_frac = _mic_delta_frac(frac_b[i] - frac_a[i], pbc)
            disp = np.dot(delta_frac, cell_avg)
            mapping.append((i, i))
            disp_vectors[i] = disp
            disp_norms[i] = float(np.linalg.norm(disp))
        return StructureMatch(mapping=mapping, displacement_vectors=disp_vectors, displacement_norms=disp_norms)

    symbols_unique = sorted(set(symbols_a))
    index_map_b: dict[str, list[int]] = {}
    for idx, symbol in enumerate(symbols_b):
        index_map_b.setdefault(symbol, []).append(idx)

    mapping_by_i: dict[int, int] = {}
    for symbol in symbols_unique:
        idxs_a = [idx for idx, value in enumerate(symbols_a) if value == symbol]
        remaining_b = list(index_map_b.get(symbol, []))
        if len(idxs_a) != len(remaining_b):
            raise ValueError(f"Cannot match element {symbol}: {len(idxs_a)} != {len(remaining_b)}")

        for i in idxs_a:
            best_j = None
            best_norm = None
            best_disp = None
            for j in remaining_b:
                delta_frac = _mic_delta_frac(frac_b[j] - frac_a[i], pbc)
                disp = np.dot(delta_frac, cell_avg)
                disp_norm = float(np.linalg.norm(disp))
                if best_norm is None or disp_norm < best_norm - 1.0e-12 or (
                    abs(disp_norm - best_norm) <= 1.0e-12 and j < best_j
                ):
                    best_j = j
                    best_norm = disp_norm
                    best_disp = disp
            assert best_j is not None
            mapping_by_i[i] = best_j
            remaining_b.remove(best_j)
            disp_vectors[i] = best_disp
            disp_norms[i] = float(best_norm)

    for i in range(len(symbols_a)):
        mapping.append((i, mapping_by_i[i]))
    return StructureMatch(mapping=mapping, displacement_vectors=disp_vectors, displacement_norms=disp_norms)


def rms_displacement(displacements: np.ndarray) -> float:
    values = np.asarray(displacements, dtype=float)
    if values.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(values**2)))


def max_displacement(displacements: np.ndarray) -> float:
    values = np.asarray(displacements, dtype=float)
    if values.size == 0:
        return 0.0
    return float(np.max(values))


def topk_pair_distance_deltas(
    atoms_a: Atoms,
    atoms_b: Atoms,
    topk: int = 20,
    r_cut: float | None = None,
) -> list[dict[str, Any]]:
    match = match_structures(atoms_a, atoms_b)
    map_b = {i: j for i, j in match.mapping}
    symbols_a = [_normalize_symbol(symbol) for symbol in atoms_a.get_chemical_symbols()]
    pos_a = atoms_a.get_positions()
    pos_b = atoms_b.get_positions()
    cell_a = atoms_a.get_cell()
    cell_b = atoms_b.get_cell()
    pbc_a = atoms_a.get_pbc()
    pbc_b = atoms_b.get_pbc()

    rows: list[dict[str, Any]] = []
    n_atoms = len(symbols_a)
    for i in range(n_atoms):
        for j in range(i + 1, n_atoms):
            b_i = map_b[i]
            b_j = map_b[j]
            d0 = float(get_distances(pos_a[i], pos_a[j], cell_a, pbc=pbc_a)[1][0][0])
            d1 = float(get_distances(pos_b[b_i], pos_b[b_j], cell_b, pbc=pbc_b)[1][0][0])
            if r_cut is not None and d0 > float(r_cut) and d1 > float(r_cut):
                continue
            pair = "-".join(_normalize_pair(symbols_a[i], symbols_a[j]))
            delta = float(d1 - d0)
            rows.append(
                {
                    "pair": pair,
                    "i": int(i),
                    "j": int(j),
                    "d0": d0,
                    "d1": d1,
                    "delta": delta,
                    "abs_delta": float(abs(delta)),
                }
            )
    rows.sort(key=lambda row: (-row["abs_delta"], row["i"], row["j"], row["pair"]))
    if topk is not None:
        return rows[: int(topk)]
    return rows


def simple_coordination_stats(
    atoms: Atoms,
    *,
    r_cut_by_pair: dict[tuple[str, str], float] | None = None,
    global_r_cut: float = 3.0,
) -> dict[str, Any]:
    symbols = [_normalize_symbol(symbol) for symbol in atoms.get_chemical_symbols()]
    positions = atoms.get_positions()
    cell = atoms.get_cell()
    pbc = atoms.get_pbc()
    counts = np.zeros(len(symbols), dtype=int)

    normalized_cutoffs: dict[tuple[str, str], float] = {}
    if r_cut_by_pair:
        for pair, cutoff in r_cut_by_pair.items():
            normalized_cutoffs[_normalize_pair(*pair)] = float(cutoff)

    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            pair = _normalize_pair(symbols[i], symbols[j])
            cutoff = normalized_cutoffs.get(pair, float(global_r_cut))
            distance = float(get_distances(positions[i], positions[j], cell, pbc=pbc)[1][0][0])
            if distance <= cutoff:
                counts[i] += 1
                counts[j] += 1

    per_element: dict[str, dict[str, float]] = {}
    for symbol in sorted(set(symbols)):
        idxs = [idx for idx, item in enumerate(symbols) if item == symbol]
        element_counts = counts[idxs].astype(float)
        per_element[symbol] = {
            "mean": float(np.mean(element_counts)),
            "min": float(np.min(element_counts)),
            "max": float(np.max(element_counts)),
            "std": float(np.std(element_counts)),
            "n_atoms": int(len(idxs)),
        }

    return {
        "global_r_cut": float(global_r_cut),
        "per_element": per_element,
    }


def spacegroup(atoms: Atoms, symprec: float = 1.0e-2, angle_tolerance: float = 5.0) -> dict[str, Any] | None:
    try:
        import spglib
    except Exception:
        return None

    dataset = spglib.get_symmetry_dataset(
        (
            np.asarray(atoms.get_cell().array, dtype=float),
            np.asarray(atoms.get_scaled_positions(wrap=True), dtype=float),
            np.asarray(atoms.get_atomic_numbers(), dtype=int),
        ),
        symprec=float(symprec),
        angle_tolerance=float(angle_tolerance),
    )
    if dataset is None:
        return None

    number = getattr(dataset, "number", None)
    international = getattr(dataset, "international", None)
    hall = getattr(dataset, "hall", None)
    return {
        "number": int(number) if number is not None else None,
        "symbol": str(international) if international is not None else None,
        "hall": str(hall) if hall is not None else None,
    }


@dataclass(frozen=True)
class VisualDeltaResult:
    rms_displacement_angstrom: float
    max_displacement_angstrom: float
    per_element_rms: dict[str, float]
    spacegroup_baseline: dict[str, Any] | None
    spacegroup_spp: dict[str, Any] | None
    spacegroup_changed: bool
    top_pair_distance_deltas: list[dict[str, Any]]
    coordination_baseline: dict[str, Any]
    coordination_spp: dict[str, Any]
    coordination_mean_delta: dict[str, float]
    cell_lengths_baseline: list[float]
    cell_angles_baseline: list[float]
    cell_lengths_spp: list[float]
    cell_angles_spp: list[float]
    cell_lengths_delta: list[float]
    cell_angles_delta: list[float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "rms_displacement_angstrom": float(self.rms_displacement_angstrom),
            "max_displacement_angstrom": float(self.max_displacement_angstrom),
            "per_element_rms": self.per_element_rms,
            "spacegroup_baseline": self.spacegroup_baseline,
            "spacegroup_spp": self.spacegroup_spp,
            "spacegroup_changed": bool(self.spacegroup_changed),
            "top_pair_distance_deltas": self.top_pair_distance_deltas,
            "coordination_baseline": self.coordination_baseline,
            "coordination_spp": self.coordination_spp,
            "coordination_mean_delta": self.coordination_mean_delta,
            "cell_lengths_baseline": self.cell_lengths_baseline,
            "cell_angles_baseline": self.cell_angles_baseline,
            "cell_lengths_spp": self.cell_lengths_spp,
            "cell_angles_spp": self.cell_angles_spp,
            "cell_lengths_delta": self.cell_lengths_delta,
            "cell_angles_delta": self.cell_angles_delta,
        }


def compute_visual_delta(
    atoms_baseline: Atoms,
    atoms_spp: Atoms,
    *,
    topk_pairs: int = 20,
    r_cut: float = 4.0,
    sg_symprec: float = 1.0e-2,
    sg_angle_tolerance: float = 5.0,
    coordination_r_cut: float | None = None,
) -> VisualDeltaResult:
    match = match_structures(atoms_baseline, atoms_spp)
    disp_norms = np.asarray(match.displacement_norms, dtype=float)
    symbols = [_normalize_symbol(symbol) for symbol in atoms_baseline.get_chemical_symbols()]

    per_element_rms: dict[str, float] = {}
    for symbol in sorted(set(symbols)):
        idxs = [idx for idx, value in enumerate(symbols) if value == symbol]
        per_element_rms[symbol] = rms_displacement(disp_norms[idxs])

    sg_baseline = spacegroup(atoms_baseline, symprec=sg_symprec, angle_tolerance=sg_angle_tolerance)
    sg_spp = spacegroup(atoms_spp, symprec=sg_symprec, angle_tolerance=sg_angle_tolerance)
    sg_changed = (
        sg_baseline is not None
        and sg_spp is not None
        and sg_baseline.get("number") is not None
        and sg_spp.get("number") is not None
        and int(sg_baseline["number"]) != int(sg_spp["number"])
    )

    coord_cut = float(r_cut if coordination_r_cut is None else coordination_r_cut)
    coord_baseline = simple_coordination_stats(atoms_baseline, global_r_cut=coord_cut)
    coord_spp = simple_coordination_stats(atoms_spp, global_r_cut=coord_cut)

    coord_delta: dict[str, float] = {}
    all_elements = sorted(
        set(coord_baseline["per_element"].keys()) | set(coord_spp["per_element"].keys())
    )
    for element in all_elements:
        mean_a = float(coord_baseline["per_element"].get(element, {}).get("mean", 0.0))
        mean_b = float(coord_spp["per_element"].get(element, {}).get("mean", 0.0))
        coord_delta[element] = float(mean_b - mean_a)

    lengths_baseline = [float(value) for value in atoms_baseline.get_cell().lengths()]
    lengths_spp = [float(value) for value in atoms_spp.get_cell().lengths()]
    angles_baseline = [float(value) for value in atoms_baseline.get_cell().angles()]
    angles_spp = [float(value) for value in atoms_spp.get_cell().angles()]

    return VisualDeltaResult(
        rms_displacement_angstrom=rms_displacement(disp_norms),
        max_displacement_angstrom=max_displacement(disp_norms),
        per_element_rms=per_element_rms,
        spacegroup_baseline=sg_baseline,
        spacegroup_spp=sg_spp,
        spacegroup_changed=bool(sg_changed),
        top_pair_distance_deltas=topk_pair_distance_deltas(
            atoms_baseline, atoms_spp, topk=topk_pairs, r_cut=r_cut
        ),
        coordination_baseline=coord_baseline,
        coordination_spp=coord_spp,
        coordination_mean_delta=coord_delta,
        cell_lengths_baseline=lengths_baseline,
        cell_angles_baseline=angles_baseline,
        cell_lengths_spp=lengths_spp,
        cell_angles_spp=angles_spp,
        cell_lengths_delta=[
            float(lengths_spp[idx] - lengths_baseline[idx]) for idx in range(3)
        ],
        cell_angles_delta=[float(angles_spp[idx] - angles_baseline[idx]) for idx in range(3)],
    )
