"""Round-trip consistency tests between g(r) and phi(r)."""

from __future__ import annotations

import numpy as np
from ase import Atoms

from spp_maker.fit_hist import make_uniform_binning
from spp_maker.supercell_gr import (
    build_supercell,
    compute_pair_histograms_supercell,
    normalize_to_g_of_r,
    species_counts,
)


def test_gr_phi_exp_roundtrip_matches_g_with_eps_behavior() -> None:
    unit = Atoms(
        "NaCl",
        positions=[[0.0, 0.0, 0.0], [2.82, 2.82, 2.82]],
        cell=[5.64, 5.64, 5.64],
        pbc=True,
    )
    edges = make_uniform_binning(d_min=0.0, d_max=10.0, bin_width=0.05).edges
    build = build_supercell(unit, target_len=20.0, r_max=10.0, sigma=0.1)
    hist = compute_pair_histograms_supercell(
        unit_atoms=unit,
        super_atoms=build.atoms,
        edges=edges,
        r_max=10.0,
        sigma=0.1,
        truncate_sigma=3.0,
    )
    g_by_pair = normalize_to_g_of_r(
        counts=hist.counts,
        edges=edges,
        unit_cell_volume=float(unit.get_volume()),
        N_by_species_unit=species_counts(unit),
        N_by_species_super=species_counts(build.atoms),
    )

    eps = 1e-12
    for g in g_by_pair.values():
        phi = -np.log(g + eps)
        exp_minus_phi = np.exp(-phi)
        assert np.allclose(exp_minus_phi, g + eps, rtol=0.0, atol=1e-12)
        mask = g > 1e-8
        if np.any(mask):
            assert np.allclose(exp_minus_phi[mask], g[mask], rtol=1e-8, atol=1e-12)
