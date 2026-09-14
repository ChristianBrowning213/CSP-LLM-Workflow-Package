"""Gaussian bin deposition tests for supercell distance histograms."""

from __future__ import annotations

import numpy as np
from ase import Atoms

from spp_maker.fit_hist import make_uniform_binning
from spp_maker.pot_io import bin_centers
from spp_maker.supercell_gr import compute_pair_histograms_supercell


def test_single_distance_deposition_spreads_symmetrically_and_is_deterministic() -> None:
    unit = Atoms("H", positions=[[0.0, 0.0, 0.0]], cell=[20.0, 20.0, 20.0], pbc=True)
    super_atoms = Atoms("HH", positions=[[2.0, 0.0, 0.0], [20.0, 0.0, 0.0]], cell=[20.0, 20.0, 20.0], pbc=True)
    edges = make_uniform_binning(d_min=0.0, d_max=4.0, bin_width=0.05).edges

    run1 = compute_pair_histograms_supercell(
        unit_atoms=unit,
        super_atoms=super_atoms,
        edges=edges,
        r_max=4.0,
        sigma=0.1,
        truncate_sigma=3.0,
    )
    run2 = compute_pair_histograms_supercell(
        unit_atoms=unit,
        super_atoms=super_atoms,
        edges=edges,
        r_max=4.0,
        sigma=0.1,
        truncate_sigma=3.0,
    )

    assert run1.pair_count_used == 1
    assert run1.pair_count_used == run2.pair_count_used
    key = ("H", "H")
    assert np.array_equal(run1.counts[key], run2.counts[key])

    values = run1.counts[key]
    assert np.count_nonzero(values > 0.0) > 1

    centers = bin_centers(edges)
    d = 2.0
    dist = np.abs(centers - d)
    order = np.argsort(dist)
    i0, i1 = int(order[0]), int(order[1])
    assert np.isclose(dist[i0], dist[i1], atol=1e-12)
    assert np.isclose(values[i0], values[i1], rtol=0.0, atol=1e-12)
