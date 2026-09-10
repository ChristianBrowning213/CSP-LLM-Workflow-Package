"""Periodic distance and neighbor edge utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from ase import Atoms


@dataclass(frozen=True)
class NeighborEdge:
    """Undirected neighbor edge with scalar distance in Angstrom."""

    i: int
    j: int
    d: float


def pairwise_mic_distances(atoms: Atoms) -> np.ndarray:
    """
    Return the full NxN minimum-image distance matrix.

    The diagonal is explicitly set to zero.
    """
    distances = np.asarray(atoms.get_all_distances(mic=True), dtype=float)
    if distances.ndim != 2 or distances.shape[0] != distances.shape[1]:
        raise ValueError(
            f"ASE returned invalid distance matrix shape {tuple(distances.shape)}; expected (N, N)."
        )
    np.fill_diagonal(distances, 0.0)
    return distances


def _validate_inputs(
    *,
    r_cut: Optional[float],
    k: Optional[int],
    min_d: Optional[float],
) -> None:
    if r_cut is None and k is None:
        raise ValueError("Either r_cut or k must be provided.")
    if r_cut is not None and r_cut <= 0:
        raise ValueError(f"r_cut must be > 0, got {r_cut}.")
    if k is not None and k <= 0:
        raise ValueError(f"k must be > 0, got {k}.")
    if min_d is not None and min_d < 0:
        raise ValueError(f"min_d must be >= 0, got {min_d}.")


def _passes_min_d(distance: float, min_d: Optional[float]) -> bool:
    return min_d is None or distance >= min_d


def _build_edges_with_cutoff(
    distances: np.ndarray,
    *,
    r_cut: float,
    min_d: Optional[float],
    include_self: bool,
) -> list[NeighborEdge]:
    n_atoms = distances.shape[0]
    edges: list[NeighborEdge] = []

    for i in range(n_atoms):
        j_start = i if include_self else i + 1
        for j in range(j_start, n_atoms):
            d_ij = float(distances[i, j])
            if d_ij <= r_cut and _passes_min_d(d_ij, min_d):
                edges.append(NeighborEdge(i=i, j=j, d=d_ij))

    edges.sort(key=lambda edge: (edge.i, edge.j))
    return edges


def _build_edges_with_knn(
    distances: np.ndarray,
    *,
    k: int,
    min_d: Optional[float],
    include_self: bool,
) -> list[NeighborEdge]:
    n_atoms = distances.shape[0]
    edge_to_distance: dict[tuple[int, int], float] = {}

    for i in range(n_atoms):
        # Stable tie-break: nearest distance first, then atom index.
        order = sorted(
            (j for j in range(n_atoms) if j != i),
            key=lambda j: (float(distances[i, j]), j),
        )
        for j in order[:k]:
            edge = (min(i, j), max(i, j))
            d_ij = float(distances[i, j])
            if _passes_min_d(d_ij, min_d):
                previous = edge_to_distance.get(edge)
                if previous is None or d_ij < previous:
                    edge_to_distance[edge] = d_ij

    if include_self:
        for i in range(n_atoms):
            d_ii = float(distances[i, i])
            if _passes_min_d(d_ii, min_d):
                edge_to_distance[(i, i)] = d_ii

    return [
        NeighborEdge(i=i, j=j, d=edge_to_distance[(i, j)])
        for (i, j) in sorted(edge_to_distance)
    ]


def build_neighbor_edges(
    atoms: Atoms,
    *,
    r_cut: Optional[float] = None,
    k: Optional[int] = None,
    min_d: Optional[float] = None,
    include_self: bool = False,
) -> list[NeighborEdge]:
    """
    Build a unique undirected edge list under periodic minimum-image distances.

    Selection mode:
    - If `r_cut` is provided, include edges with `d <= r_cut`.
    - Else if `k` is provided, include k nearest neighbors per atom.
    - Else raise ValueError.

    Edges are deterministic and sorted by `(i, j)`.
    """
    _validate_inputs(r_cut=r_cut, k=k, min_d=min_d)
    distances = pairwise_mic_distances(atoms)

    if r_cut is not None:
        return _build_edges_with_cutoff(
            distances,
            r_cut=float(r_cut),
            min_d=min_d,
            include_self=include_self,
        )

    # If r_cut is None, validation guarantees k is not None.
    assert k is not None
    return _build_edges_with_knn(
        distances,
        k=int(k),
        min_d=min_d,
        include_self=include_self,
    )
