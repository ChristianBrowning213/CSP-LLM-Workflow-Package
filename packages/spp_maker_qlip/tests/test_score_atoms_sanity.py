"""Sanity checks for score_atoms behavior."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from spp_maker.export import export_spp_root
from spp_maker.fit_hist import accumulate_histograms
from spp_maker.fit_phi import build_phi_from_hist
from spp_maker.io_cif import load_cif
from spp_maker.score import score_atoms
from spp_maker.spp_model import load_spp_model


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "cifs"


def test_score_atoms_changes_for_symbol_perturbation(tmp_path: Path) -> None:
    nacl = load_cif(FIXTURE_DIR / "nacl.cif").atoms
    sic = load_cif(FIXTURE_DIR / "sic.cif").atoms
    hist = accumulate_histograms([nacl, sic], r_cut=8.0, d_min=0.5, d_max=8.0, bin_width=0.1)
    phi_res = build_phi_from_hist(hist, alpha=1e-3, shifted=True)

    out_root = tmp_path / "spp_model"
    export_spp_root(out_root, phi_res, name="sanity")
    model = load_spp_model(out_root)

    candidates = [
        load_cif(FIXTURE_DIR / "nacl.cif").atoms,
        load_cif(FIXTURE_DIR / "sic.cif").atoms,
    ]
    original = None
    for candidate in candidates:
        report = score_atoms(candidate, model, r_cut=8.0, use_bandpass=False)
        if report.num_edges > 0:
            original = candidate
            break
    assert original is not None

    perturbed = original.copy()
    base_symbol = original.get_chemical_symbols()[0]
    perturbed.set_chemical_symbols([base_symbol] * len(original))

    score_original = score_atoms(original, model, r_cut=8.0, use_bandpass=False)
    score_perturbed = score_atoms(perturbed, model, r_cut=8.0, use_bandpass=False)

    assert (
        not np.isclose(score_original.total, score_perturbed.total)
        or score_original.skipped_missing_pair != score_perturbed.skipped_missing_pair
    )
