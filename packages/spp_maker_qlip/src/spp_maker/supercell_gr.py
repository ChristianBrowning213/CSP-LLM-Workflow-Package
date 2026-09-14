"""Supercell-based pair histogram and g(r) utilities for Dmytro-mode fitting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Tuple

import numpy as np
from ase import Atoms

from spp_maker.fit_hist import Binning, canonical_pair
from spp_maker.pot_io import bin_centers

PairKey = Tuple[str, str]


@dataclass(frozen=True)
class SupercellBuildResult:
    """Explicit supercell construction metadata."""

    atoms: Atoms
    repeats: tuple[int, int, int]
    half_extents: tuple[float, float, float]
    min_half_extent: float
    required_support: float
    gr_support_ok: bool


@dataclass(frozen=True)
class SupercellHistogramResult:
    """Histogram payload for one unit-cell vs supercell accumulation."""

    counts: Dict[PairKey, np.ndarray]
    pair_count_used: int
    pair_count_total_est: int


def _validate_positive_finite(name: str, value: float) -> float:
    value = float(value)
    if not np.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and > 0, got {value}.")
    return value


def species_counts(atoms: Atoms) -> dict[str, int]:
    """Return deterministic species counts for one structure."""
    counts: dict[str, int] = {}
    for symbol in atoms.get_chemical_symbols():
        counts[str(symbol)] = counts.get(str(symbol), 0) + 1
    return dict(sorted(counts.items()))


def _cell_face_heights(cell: np.ndarray) -> np.ndarray:
    """
    Return unit-cell face-to-face heights (h_a, h_b, h_c).

    For vector a, h_a = V / |b x c| (and cyclic permutations).
    """
    a, b, c = cell[0], cell[1], cell[2]
    volume = float(abs(np.dot(a, np.cross(b, c))))
    if not np.isfinite(volume) or volume <= 0.0:
        raise ValueError("atoms must have non-degenerate unit-cell volume.")

    areas = np.asarray(
        [
            np.linalg.norm(np.cross(b, c)),
            np.linalg.norm(np.cross(c, a)),
            np.linalg.norm(np.cross(a, b)),
        ],
        dtype=np.float64,
    )
    if np.any(areas <= 0.0):
        raise ValueError("atoms must have non-zero cell face areas.")
    return volume / areas


def build_supercell(
    atoms: Atoms,
    target_len: float = 20.0,
    r_max: float = 10.0,
    sigma: float = 0.1,
    margin: float = 0.5,
    truncate_sigma: float = 3.0,
) -> SupercellBuildResult:
    """
    Build an explicit supercell that safely supports g(r) accumulation.

    The repeats are chosen to satisfy both:
    - repeated lattice lengths >= target_len (per lattice vector length)
    - repeated half-extent along each cell-normal direction >= r_max + truncate_sigma*sigma + margin
    """
    target_len = _validate_positive_finite("target_len", target_len)
    r_max = _validate_positive_finite("r_max", r_max)
    sigma = _validate_positive_finite("sigma", sigma)
    truncate_sigma = _validate_positive_finite("truncate_sigma", truncate_sigma)
    margin = float(margin)
    if not np.isfinite(margin) or margin < 0.0:
        raise ValueError(f"margin must be finite and >= 0, got {margin}.")

    cell = np.asarray(atoms.cell.array, dtype=np.float64)
    lengths = np.linalg.norm(cell, axis=1)
    if np.any(lengths <= 0.0):
        raise ValueError("atoms must have non-zero cell vectors to build a supercell.")
    heights = _cell_face_heights(cell)

    required_support = float(r_max + truncate_sigma * sigma + margin)

    repeats = np.ones(3, dtype=np.int64)
    for axis in range(3):
        by_target = int(np.ceil(target_len / lengths[axis]))
        by_support = int(np.ceil((2.0 * required_support) / heights[axis]))
        repeats[axis] = max(1, by_target, by_support)
    repeat_tuple = (int(repeats[0]), int(repeats[1]), int(repeats[2]))

    super_atoms = atoms.repeat(repeat_tuple)

    # Center repeated images so translations cover positive and negative directions.
    offset = (
        (repeat_tuple[0] // 2) * cell[0]
        + (repeat_tuple[1] // 2) * cell[1]
        + (repeat_tuple[2] // 2) * cell[2]
    )
    super_atoms.positions = np.asarray(super_atoms.positions, dtype=np.float64) - offset

    half_extents = tuple(
        float(0.5 * repeat_tuple[i] * heights[i]) for i in range(3)
    )
    min_half_extent = float(min(half_extents))
    gr_support_ok = bool(all(value >= required_support - 1e-12 for value in half_extents))

    super_atoms.info["supercell_repeats"] = repeat_tuple
    super_atoms.info["supercell_half_extents"] = half_extents
    super_atoms.info["supercell_min_half_extent"] = min_half_extent
    super_atoms.info["gr_required_support"] = required_support
    super_atoms.info["gr_support_ok"] = gr_support_ok

    return SupercellBuildResult(
        atoms=super_atoms,
        repeats=repeat_tuple,
        half_extents=half_extents,
        min_half_extent=min_half_extent,
        required_support=required_support,
        gr_support_ok=gr_support_ok,
    )


def compute_pair_histograms_supercell(
    unit_atoms: Atoms,
    super_atoms: Atoms,
    edges: np.ndarray,
    r_max: float = 10.0,
    sigma: float = 0.1,
    truncate_sigma: float = 3.0,
    max_pairs: int | None = None,
) -> SupercellHistogramResult:
    """
    Compute Gaussian-smeared pair-distance histograms from unit -> supercell atoms.

    Distances > r_max and self distances (~0) are ignored.
    Each accepted distance contributes to nearby bins:
      exp(-0.5 * ((r_k - d) / sigma)^2)
    for bin centers r_k in [d - truncate_sigma*sigma, d + truncate_sigma*sigma].
    If max_pairs is set, distances are consumed in deterministic i->j order and
    truncated after max_pairs accepted distances.
    """
    r_max = _validate_positive_finite("r_max", r_max)
    sigma = _validate_positive_finite("sigma", sigma)
    truncate_sigma = _validate_positive_finite("truncate_sigma", truncate_sigma)
    if max_pairs is not None and int(max_pairs) <= 0:
        raise ValueError(f"max_pairs must be > 0 when provided, got {max_pairs}.")

    binning = Binning(edges=np.asarray(edges, dtype=np.float64))
    centers = bin_centers(binning.edges)

    unit_symbols = tuple(unit_atoms.get_chemical_symbols())
    super_symbols = tuple(super_atoms.get_chemical_symbols())
    unit_pos = np.asarray(unit_atoms.get_positions(), dtype=np.float64)
    super_pos = np.asarray(super_atoms.get_positions(), dtype=np.float64)

    n_unit = len(unit_symbols)
    n_super = len(super_symbols)
    pair_count_total_est = max(0, n_unit * max(0, n_super - 1))

    counts: Dict[PairKey, np.ndarray] = {}
    pair_count_used = 0
    eps_self = 1e-12
    radius = float(truncate_sigma * sigma)
    reached_cap = False
    cap = None if max_pairs is None else int(max_pairs)

    for i, symbol_i in enumerate(unit_symbols):
        if reached_cap:
            break
        pos_i = unit_pos[i]
        for j, symbol_j in enumerate(super_symbols):
            d = float(np.linalg.norm(super_pos[j] - pos_i))
            if d <= eps_self or d > r_max:
                continue

            if cap is not None and pair_count_used >= cap:
                reached_cap = True
                break

            pair_count_used += 1
            key = canonical_pair(str(symbol_i), str(symbol_j))
            if key not in counts:
                counts[key] = np.zeros(binning.nbins, dtype=np.float64)

            lo = int(np.searchsorted(centers, d - radius, side="left"))
            hi = int(np.searchsorted(centers, d + radius, side="right"))
            if lo >= hi:
                continue

            r_local = centers[lo:hi]
            weights = np.exp(-0.5 * ((r_local - d) / sigma) ** 2)
            counts[key][lo:hi] += weights.astype(np.float64, copy=False)

    return SupercellHistogramResult(
        counts=counts,
        pair_count_used=int(pair_count_used),
        pair_count_total_est=int(pair_count_total_est),
    )


def normalize_to_g_of_r(
    counts: Dict[PairKey, np.ndarray],
    edges: np.ndarray,
    unit_cell_volume: float,
    N_by_species_unit: Mapping[str, int],
    N_by_species_super: Mapping[str, int],
) -> Dict[PairKey, np.ndarray]:
    """
    Convert pair histogram counts to g(r) using shell-volume normalization.

    Convention:
    - shell(r_k) = 4*pi*r_k^2*dr_k
    - supercell volume V_super = V_unit * (N_super_total / N_unit_total)
    - rho_super(X) = N_super(X) / V_super
    - canonical pair counts for A!=B are interpreted as merged directed counts:
        A(unit)->B(super) + B(unit)->A(super)
      so denominator uses:
        N_unit(A)*rho_super(B) + N_unit(B)*rho_super(A)
      and for A==B:
        N_unit(A)*rho_super(A)
    """
    volume_unit = float(unit_cell_volume)
    if not np.isfinite(volume_unit) or volume_unit <= 0:
        raise ValueError(f"unit_cell_volume must be finite and > 0, got {unit_cell_volume}.")

    n_unit_total = int(sum(int(v) for v in N_by_species_unit.values()))
    n_super_total = int(sum(int(v) for v in N_by_species_super.values()))
    if n_unit_total <= 0 or n_super_total <= 0:
        raise ValueError("species counts must include at least one atom in unit and supercell.")
    repeat_factor = float(n_super_total) / float(n_unit_total)
    if repeat_factor <= 0.0:
        raise ValueError("invalid repeat factor inferred from species counts.")
    volume_super = volume_unit * repeat_factor

    binning = Binning(edges=np.asarray(edges, dtype=np.float64))
    centers = bin_centers(binning.edges)
    dr = np.diff(binning.edges)
    shell_vol = 4.0 * np.pi * (centers**2) * dr

    g_by_pair: Dict[PairKey, np.ndarray] = {}
    for key in sorted(counts):
        a, b = key
        values = np.asarray(counts[key], dtype=np.float64)
        if values.shape != (binning.nbins,):
            raise ValueError(
                f"Histogram counts for pair {key} must have shape ({binning.nbins},), got {values.shape}."
            )
        if not np.all(np.isfinite(values)):
            raise ValueError(f"Histogram counts for pair {key} must be finite.")
        if np.any(values < 0):
            raise ValueError(f"Histogram counts for pair {key} must be >= 0.")

        n_a_unit = float(int(N_by_species_unit.get(a, 0)))
        n_b_unit = float(int(N_by_species_unit.get(b, 0)))
        rho_a_super = float(int(N_by_species_super.get(a, 0))) / volume_super
        rho_b_super = float(int(N_by_species_super.get(b, 0))) / volume_super

        prefactor = (
            n_a_unit * rho_b_super if a == b else (n_a_unit * rho_b_super + n_b_unit * rho_a_super)
        )
        denom = prefactor * shell_vol

        g = np.zeros_like(values, dtype=np.float64)
        valid = denom > 0.0
        if np.any(valid):
            g[valid] = values[valid] / denom[valid]
        g_by_pair[key] = g

    return g_by_pair
