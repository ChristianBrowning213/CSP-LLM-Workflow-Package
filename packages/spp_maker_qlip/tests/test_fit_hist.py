"""Tests for pairwise histogram accumulation."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from spp_maker.fit_hist import accumulate_histograms, make_uniform_binning
from spp_maker.io_cif import load_cif


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "cifs"


def _load_fixture_atoms() -> list:
    return [
        load_cif(FIXTURE_DIR / "nacl.cif").atoms,
        load_cif(FIXTURE_DIR / "sic.cif").atoms,
    ]


def test_make_uniform_binning_properties() -> None:
    binning = make_uniform_binning(d_min=0.5, d_max=2.0, bin_width=0.3)

    expected_nbins = int(np.ceil((2.0 - 0.5) / 0.3))
    assert binning.nbins == expected_nbins
    assert np.all(np.diff(binning.edges) > 0.0)
    assert np.isclose(binning.edges[0], 0.5, atol=1e-12)
    assert np.isclose(binning.edges[-1], 2.0, atol=1e-12)


def test_accumulate_histograms_symmetry_and_nonneg() -> None:
    atoms_list = _load_fixture_atoms()
    acc = accumulate_histograms(atoms_list, r_cut=4.0)

    assert acc.counts
    for key, values in acc.counts.items():
        assert key[0] <= key[1]
        assert values.shape == (acc.binning.nbins,)
        assert np.all(values >= 0.0)


def test_species_whitelist_filters() -> None:
    atoms_list = _load_fixture_atoms()
    acc = accumulate_histograms(
        atoms_list,
        r_cut=4.0,
        species_whitelist=["Xe"],
    )

    assert not acc.counts or all(np.all(v == 0.0) for v in acc.counts.values())


def test_structure_weights_affect_totals() -> None:
    atoms_list = _load_fixture_atoms()
    base = accumulate_histograms(atoms_list, r_cut=4.0, structure_weights=[1.0, 1.0])
    only_first = accumulate_histograms([atoms_list[0]], r_cut=4.0, structure_weights=[1.0])
    only_second = accumulate_histograms([atoms_list[1]], r_cut=4.0, structure_weights=[1.0])

    if only_first.total_pairs_seen > 0:
        weighted = accumulate_histograms(atoms_list, r_cut=4.0, structure_weights=[2.0, 1.0])
    elif only_second.total_pairs_seen > 0:
        weighted = accumulate_histograms(atoms_list, r_cut=4.0, structure_weights=[1.0, 2.0])
    else:
        raise AssertionError("Expected at least one structure to produce edges at r_cut=4.0.")

    assert base.total_pairs_seen > 0
    assert weighted.total_weighted_pairs_seen > base.total_weighted_pairs_seen
