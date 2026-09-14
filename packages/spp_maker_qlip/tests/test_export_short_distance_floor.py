"""Tests for export-time short-distance guardrail flooring."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from spp_maker.export import export_spp_root
from spp_maker.fit_hist import accumulate_histograms
from spp_maker.fit_phi import build_phi_from_hist
from spp_maker.io_cif import load_cif
from spp_maker.pot_io import read_pot_like_qlip


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "cifs"


def _make_phi_result():
    atoms_list = [
        load_cif(FIXTURE_DIR / "nacl.cif").atoms,
        load_cif(FIXTURE_DIR / "sic.cif").atoms,
    ]
    hist = accumulate_histograms(
        atoms_list,
        r_cut=8.0,
        d_min=0.5,
        d_max=8.0,
        bin_width=0.1,
    )
    return build_phi_from_hist(hist, alpha=1e-3, shifted=True)


def test_export_short_distance_floor_applies_and_records_manifest(tmp_path: Path) -> None:
    phi_res = _make_phi_result()
    out_root = tmp_path / "spp_guarded"
    floor = 3.0

    export_spp_root(
        out_root=out_root,
        phi_res=phi_res,
        short_distance_floor=floor,
        short_distance_bins=2,
    )

    manifest = json.loads((out_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["short_distance_floor"] == floor
    assert manifest["short_distance_bins"] == 2
    assert manifest["short_distance_r_max"] is None

    pair_entry = manifest["pairs"][0]
    pot_path = out_root / pair_entry["path"]
    _, u = read_pot_like_qlip(pot_path)
    assert u.shape[0] >= 2
    assert np.all(u[:2] >= floor)

    text = pot_path.read_text(encoding="utf-8")
    assert "short_distance_floor" in text
