"""Tests for periodic neighbor graph construction."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from spp_maker.io_cif import load_cif
from spp_maker.neighbors import build_neighbor_edges, pairwise_mic_distances


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "cifs"


def test_pairwise_mic_distances_shape_and_diagonal() -> None:
    atoms = load_cif(FIXTURE_DIR / "nacl.cif").atoms
    distances = pairwise_mic_distances(atoms)

    n_atoms = len(atoms)
    assert distances.shape == (n_atoms, n_atoms)
    assert np.allclose(np.diag(distances), 0.0, atol=1e-12)


def test_build_edges_r_cut_unique_sorted_no_self() -> None:
    atoms = load_cif(FIXTURE_DIR / "nacl.cif").atoms
    edges = build_neighbor_edges(atoms, r_cut=8.0)

    assert edges
    pairs = [(edge.i, edge.j) for edge in edges]
    assert all(i < j for i, j in pairs)
    assert pairs == sorted(pairs)
    assert len(pairs) == len(set(pairs))
    assert all(edge.d > 0.0 for edge in edges)


def test_build_edges_min_d_excludes() -> None:
    atoms = load_cif(FIXTURE_DIR / "nacl.cif").atoms
    baseline = build_neighbor_edges(atoms, r_cut=20.0, include_self=True)
    filtered = build_neighbor_edges(atoms, r_cut=20.0, min_d=1e-6, include_self=True)

    assert len(filtered) < len(baseline)
    assert all(edge.d >= 1e-6 for edge in filtered)


def test_build_edges_knn_unique() -> None:
    atoms = load_cif(FIXTURE_DIR / "sic.cif").atoms
    edges = build_neighbor_edges(atoms, k=2)

    pairs = [(edge.i, edge.j) for edge in edges]
    assert all(i < j for i, j in pairs)
    assert len(pairs) == len(set(pairs))
    assert all(edge.d > 0.0 for edge in edges)


def test_build_edges_requires_r_cut_or_k() -> None:
    atoms = load_cif(FIXTURE_DIR / "sic.cif").atoms

    with pytest.raises(ValueError, match="Either r_cut or k must be provided."):
        build_neighbor_edges(atoms)
