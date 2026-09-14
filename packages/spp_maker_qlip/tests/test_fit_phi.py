"""Tests for histogram-to-phi conversion."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from spp_maker.fit_hist import HistAccumulator, accumulate_histograms, make_uniform_binning
from spp_maker.fit_phi import build_phi_from_hist
from spp_maker.io_cif import load_cif


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "cifs"


def _fixture_atoms() -> list:
    return [
        load_cif(FIXTURE_DIR / "nacl.cif").atoms,
        load_cif(FIXTURE_DIR / "sic.cif").atoms,
    ]


def test_build_phi_from_hist_shapes_sums_and_finiteness() -> None:
    hist = accumulate_histograms(
        _fixture_atoms(),
        r_cut=4.0,
        d_min=0.5,
        d_max=8.0,
        bin_width=0.1,
    )
    result = build_phi_from_hist(hist, alpha=1e-3, shifted=True)

    npairs = len(result.pairs)
    nbins = result.binning.nbins
    assert result.p.shape == (npairs, nbins)
    assert result.phi.shape == (npairs, nbins)
    assert result.counts.shape == (npairs, nbins)

    if npairs > 0:
        assert np.allclose(np.sum(result.p, axis=1), 1.0, atol=1e-12)
        assert np.all(np.isfinite(result.phi))
        assert np.all(result.phi >= -1e-12)
        assert np.allclose(np.min(result.phi, axis=1), 0.0, atol=1e-12)


def test_build_phi_from_hist_is_deterministic() -> None:
    hist = accumulate_histograms(
        _fixture_atoms(),
        r_cut=4.0,
        d_min=0.5,
        d_max=8.0,
        bin_width=0.1,
    )
    r1 = build_phi_from_hist(hist, alpha=1e-3, shifted=True)
    r2 = build_phi_from_hist(hist, alpha=1e-3, shifted=True)

    assert r1.pairs == r2.pairs
    assert np.array_equal(r1.counts, r2.counts)
    assert np.array_equal(r1.p, r2.p)
    assert np.array_equal(r1.phi, r2.phi)


def test_zero_counts_pair_gives_uniform_p_and_zero_shifted_phi() -> None:
    binning = make_uniform_binning(d_min=0.5, d_max=1.5, bin_width=0.25)
    key = ("A", "B")
    hist = HistAccumulator(
        binning=binning,
        counts={key: np.zeros(binning.nbins, dtype=np.float64)},
        total_pairs_seen=0,
        total_weighted_pairs_seen=0.0,
    )

    result = build_phi_from_hist(hist, alpha=1e-3, shifted=True)
    idx = result.index_of(key)

    expected_p = np.full((binning.nbins,), 1.0 / binning.nbins, dtype=np.float64)
    assert np.allclose(result.p[idx], expected_p, atol=1e-12)
    assert np.allclose(result.phi[idx], result.phi[idx][0], atol=1e-12)
    assert np.allclose(result.phi[idx], 0.0, atol=1e-12)
