"""Tests for supercell-based g(r) histogram utilities."""

from __future__ import annotations

import numpy as np
from ase import Atoms

from spp_maker.fit_hist import make_uniform_binning
from spp_maker.pot_io import bin_centers
from spp_maker.supercell_gr import (
    build_supercell,
    compute_pair_histograms_supercell,
    normalize_to_g_of_r,
)


def test_build_supercell_repeats_meet_target_len() -> None:
    atoms = Atoms("Na", positions=[[0.0, 0.0, 0.0]], cell=[3.0, 4.0, 5.0], pbc=True)
    build = build_supercell(atoms, target_len=10.0, r_max=2.0, sigma=0.1)

    repeats = build.repeats
    assert repeats == (4, 3, 2) or repeats == (5, 4, 3)
    assert build.gr_support_ok

    lengths = np.asarray([3.0, 4.0, 5.0], dtype=np.float64) * np.asarray(repeats, dtype=np.float64)
    assert np.all(lengths >= 10.0)


def test_gaussian_deposition_spreads_across_bins_and_is_deterministic() -> None:
    unit = Atoms("H", positions=[[0.0, 0.0, 0.0]], cell=[5.0, 5.0, 5.0], pbc=True)
    super_atoms = build_supercell(unit, target_len=15.0).atoms
    edges = make_uniform_binning(d_min=0.0, d_max=6.0, bin_width=0.05).edges

    run1 = compute_pair_histograms_supercell(unit, super_atoms, edges, r_max=6.0, sigma=0.1)
    run2 = compute_pair_histograms_supercell(unit, super_atoms, edges, r_max=6.0, sigma=0.1)

    key = ("H", "H")
    assert run1.pair_count_used > 0
    assert run1.pair_count_used == run2.pair_count_used
    assert key in run1.counts
    assert np.array_equal(run1.counts[key], run2.counts[key])

    values = run1.counts[key]
    nonzero = np.flatnonzero(values > 0.0)
    assert nonzero.size > 1

    centers = bin_centers(edges)
    peak_r = float(centers[int(np.argmax(values))])
    assert 4.8 <= peak_r <= 5.2


def test_normalize_to_g_of_r_is_finite_and_nonnegative() -> None:
    unit = Atoms("H", positions=[[0.0, 0.0, 0.0]], cell=[5.0, 5.0, 5.0], pbc=True)
    super_atoms = build_supercell(unit, target_len=15.0).atoms
    edges = make_uniform_binning(d_min=0.0, d_max=6.0, bin_width=0.05).edges
    hist = compute_pair_histograms_supercell(unit, super_atoms, edges, r_max=6.0, sigma=0.1)

    g_of_r = normalize_to_g_of_r(
        hist.counts,
        edges,
        unit_cell_volume=float(unit.get_volume()),
        N_by_species_unit={"H": 1},
        N_by_species_super={"H": len(super_atoms)},
    )
    key = ("H", "H")
    assert key in g_of_r
    assert np.all(np.isfinite(g_of_r[key]))
    assert np.all(g_of_r[key] >= 0.0)
