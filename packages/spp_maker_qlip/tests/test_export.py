"""Tests for SPP export layout and manifest writing."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from spp_maker.export import export_spp_root
from spp_maker.fit_hist import accumulate_histograms
from spp_maker.fit_phi import build_phi_from_hist
from spp_maker.io_cif import load_cif
from spp_maker.pot_io import bin_centers, read_pot_like_qlip


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "cifs"


def _make_phi_result():
    atoms_list = [
        load_cif(FIXTURE_DIR / "nacl.cif").atoms,
        load_cif(FIXTURE_DIR / "sic.cif").atoms,
    ]
    hist = accumulate_histograms(
        atoms_list,
        r_cut=4.0,
        d_min=0.5,
        d_max=8.0,
        bin_width=0.1,
    )
    return build_phi_from_hist(hist, alpha=1e-3, shifted=True)


def test_export_spp_root_layout_and_manifest(tmp_path: Path) -> None:
    phi_res = _make_phi_result()
    out_root = tmp_path / "spp_root"

    exported = export_spp_root(
        out_root=out_root,
        phi_res=phi_res,
        name="test_run",
        write_manifest=True,
        manifest_extra={"source": "pytest"},
    )

    assert exported == out_root
    manifest_path = out_root / "manifest.json"
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["name"] == "test_run"
    assert manifest["alpha"] == phi_res.alpha
    assert manifest["shifted"] == phi_res.shifted
    assert manifest["nbins"] == phi_res.binning.nbins
    assert manifest["source"] == "pytest"
    assert len(manifest["pairs"]) == len(phi_res.pairs)

    expected_r = bin_centers(phi_res.binning.edges)
    for pair_item in manifest["pairs"]:
        a = pair_item["A"]
        b = pair_item["B"]
        rel = pair_item["path"]
        expected_rel = f"{a}-{b}/{a}-{b}.POT"
        assert rel == expected_rel

        pot_path = out_root / rel
        assert pot_path.exists()
        r, u = read_pot_like_qlip(pot_path)
        assert r.shape == (phi_res.binning.nbins,)
        assert u.shape == (phi_res.binning.nbins,)
        assert np.allclose(r, expected_r, atol=1e-8)
        assert np.all(np.isfinite(u))
