"""Histogram accumulation utilities for species-pair distance statistics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple, Union

import numpy as np
from ase import Atoms

from spp_maker.neighbors import build_neighbor_edges
from spp_maker.weights import BandpassParams, bandpass_weight

PairKey = Tuple[str, str]


@dataclass(frozen=True)
class Binning:
    """Distance bin edges with utility helpers."""

    edges: np.ndarray

    def __post_init__(self) -> None:
        edges = np.asarray(self.edges, dtype=np.float64)
        if edges.ndim != 1:
            raise ValueError(f"edges must be a 1D array, got shape {tuple(edges.shape)}.")
        if edges.size < 2:
            raise ValueError("edges must contain at least two values.")
        if not np.all(np.isfinite(edges)):
            raise ValueError("edges must be finite.")
        if not np.all(np.diff(edges) > 0):
            raise ValueError("edges must be strictly increasing.")
        object.__setattr__(self, "edges", edges)

    @property
    def nbins(self) -> int:
        return int(self.edges.size - 1)

    def bin_index(self, d: Union[float, np.ndarray]) -> Union[int, np.ndarray]:
        """
        Return bin index for distances.

        Out-of-range values are mapped to -1. The right endpoint maps to the last bin.
        """
        d_arr = np.asarray(d, dtype=np.float64)
        idx = np.searchsorted(self.edges, d_arr, side="right") - 1
        valid = (
            (d_arr >= self.edges[0])
            & (d_arr <= self.edges[-1])
            & (idx >= 0)
            & (idx < self.nbins)
        )
        idx = np.where(valid, idx, -1).astype(np.int64, copy=False)

        if np.isscalar(d):
            return int(idx.item())
        return idx


def make_uniform_binning(d_min: float, d_max: float, bin_width: float) -> Binning:
    """
    Create uniform bin edges [d_min, d_max] with step bin_width.

    If `(d_max - d_min)` is not an exact multiple of `bin_width`, the final bin
    is shorter so that the right endpoint remains exactly `d_max`.
    """
    if not np.isfinite(d_min) or not np.isfinite(d_max):
        raise ValueError(f"d_min and d_max must be finite, got {d_min}, {d_max}.")
    if not np.isfinite(bin_width):
        raise ValueError(f"bin_width must be finite, got {bin_width}.")
    if d_min < 0:
        raise ValueError(f"d_min must be >= 0, got {d_min}.")
    if d_max <= d_min:
        raise ValueError(f"d_max must be > d_min, got d_max={d_max}, d_min={d_min}.")
    if bin_width <= 0:
        raise ValueError(f"bin_width must be > 0, got {bin_width}.")

    edges = np.arange(d_min, d_max + bin_width, bin_width, dtype=np.float64)
    if edges.size == 0:
        edges = np.array([d_min, d_max], dtype=np.float64)
    else:
        # Keep exact right endpoint and prevent overshoot from floating-point accumulation.
        if edges[-1] > d_max:
            edges = edges[edges < d_max]
        if edges.size == 0 or not np.isclose(edges[-1], d_max, rtol=0.0, atol=1e-12):
            edges = np.append(edges, d_max)
        else:
            edges[-1] = d_max

    if not np.isclose(edges[0], d_min, rtol=0.0, atol=1e-12):
        edges = np.insert(edges, 0, d_min)

    return Binning(edges=edges)


def canonical_pair(a: str, b: str) -> PairKey:
    """Return a canonical unordered pair key with lexicographic ordering."""
    return (a, b) if a <= b else (b, a)


@dataclass
class HistAccumulator:
    """Mutable histogram container keyed by canonical species pairs."""

    binning: Binning
    counts: Dict[PairKey, np.ndarray]
    total_pairs_seen: int
    total_weighted_pairs_seen: float

    def add_sample(self, a: str, b: str, d: float, weight: float) -> None:
        """
        Add one weighted sample to a histogram bin.

        Distances outside `[edges[0], edges[-1]]` are ignored.
        """
        if not np.isfinite(d):
            raise ValueError(f"distance must be finite, got {d}.")
        if not np.isfinite(weight):
            raise ValueError(f"weight must be finite, got {weight}.")
        if weight < 0:
            raise ValueError(f"weight must be >= 0, got {weight}.")

        idx = self.binning.bin_index(float(d))
        if idx < 0:
            return

        pair = canonical_pair(a, b)
        if pair not in self.counts:
            self.counts[pair] = np.zeros(self.binning.nbins, dtype=np.float64)
        self.counts[pair][idx] += float(weight)
        self.total_pairs_seen += 1
        self.total_weighted_pairs_seen += float(weight)


def accumulate_histograms(
    atoms_list: Sequence[Atoms],
    *,
    structure_weights: Optional[Sequence[float]] = None,
    r_cut: Optional[float] = None,
    k: Optional[int] = None,
    min_d: Optional[float] = None,
    bandpass: Optional[BandpassParams] = None,
    species_whitelist: Optional[Sequence[str]] = None,
    binning: Optional[Binning] = None,
    d_min: float = 0.5,
    d_max: float = 8.0,
    bin_width: float = 0.05,
) -> HistAccumulator:
    """
    Accumulate weighted distance histograms for canonical species pairs.

    For each structure, neighbors are generated with `build_neighbor_edges`. Each
    accepted edge contributes `structure_weight * bandpass_weight(d)` (or `1.0`
    without band-pass) to one distance bin.
    """
    if structure_weights is None:
        weights = np.ones(len(atoms_list), dtype=np.float64)
    else:
        if len(structure_weights) != len(atoms_list):
            raise ValueError(
                "structure_weights length must match atoms_list length: "
                f"{len(structure_weights)} != {len(atoms_list)}."
            )
        weights = np.asarray(structure_weights, dtype=np.float64)

    if not np.all(np.isfinite(weights)):
        raise ValueError("structure_weights must be finite.")
    if np.any(weights < 0):
        raise ValueError("structure_weights must be >= 0.")

    active_binning = binning if binning is not None else make_uniform_binning(d_min, d_max, bin_width)
    whitelist_set = set(species_whitelist) if species_whitelist is not None else None

    accumulator = HistAccumulator(
        binning=active_binning,
        counts={},
        total_pairs_seen=0,
        total_weighted_pairs_seen=0.0,
    )

    for atoms, structure_weight in zip(atoms_list, weights):
        symbols = atoms.get_chemical_symbols()
        edges = build_neighbor_edges(atoms, r_cut=r_cut, k=k, min_d=min_d)

        for edge in edges:
            a = symbols[edge.i]
            b = symbols[edge.j]
            if whitelist_set is not None and (a not in whitelist_set or b not in whitelist_set):
                continue

            if bandpass is None:
                edge_weight = 1.0
            else:
                edge_weight = float(bandpass_weight(float(edge.d), bandpass))

            accumulator.add_sample(
                a=a,
                b=b,
                d=float(edge.d),
                weight=float(structure_weight) * edge_weight,
            )

    return accumulator
